#!/usr/bin/env python3
"""GitHub API file synchronization, Python 3.9+, standard library only."""
import argparse
import base64
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

META = ".ghsync"
LIMIT = 20 * 1024 * 1024
SKIP = {META, ".git", "node_modules", ".venv", "venv", "__pycache__", ".DS_Store"}


class SyncError(Exception):
    pass


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def check_path(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise SyncError("不支持的文件路径：%r" % name)
    parts = name.split("/")
    if any(p in ("", ".", "..") or p.casefold() in (".git", META) or
           any(ord(c) < 32 or ord(c) == 127 for c in p) for p in parts):
        raise SyncError("不安全的文件路径：%r" % name)
    if PurePosixPath(name).is_absolute():
        raise SyncError("拒绝绝对路径")
    return parts


def validate_files(files):
    aliases = {}
    for name, entry in files.items():
        parts = check_path(name)
        if entry.get("mode") not in ("100644", "100755"):
            raise SyncError("第一版仅支持普通文件和可执行文件，不支持符号链接/子模块：%r" % name)
        if not re.fullmatch(r"[0-9a-f]{40}", entry.get("sha", "")):
            raise SyncError("无效的文件对象 SHA")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            alias = unicodedata.normalize("NFC", prefix).casefold()
            if alias in aliases and aliases[alias] != prefix:
                raise SyncError("macOS 大小写/Unicode 路径冲突：%r / %r" % (aliases[alias], prefix))
            aliases[alias] = prefix
        if any("/".join(parts[:i]) in files for i in range(1, len(parts))):
            raise SyncError("文件与目录路径冲突：%r" % name)


def target(root, name):
    parts = check_path(name)
    path = root
    for i, part in enumerate(parts):
        # Inspect existing siblings too: macOS may alias case or Unicode variants.
        if path.is_dir():
            key = unicodedata.normalize("NFC", part).casefold()
            for sibling in path.iterdir():
                if unicodedata.normalize("NFC", sibling.name).casefold() == key and sibling.name != part:
                    raise SyncError("本地路径别名冲突：%r" % name)
        path = path / part
        if path.is_symlink():
            raise SyncError("拒绝跟随符号链接：%r" % name)
        if i < len(parts) - 1 and path.exists() and not path.is_dir():
            raise SyncError("父路径不是目录：%r；请分步处理文件/目录转换" % name)
    return path


def read_file(root, name):
    path = target(root, name)
    if not path.exists():
        return None, None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise SyncError("不是普通文件：%r" % name)
    if info.st_size > LIMIT:
        raise SyncError("文件超过本工具 20 MiB 限制：%r" % name)
    data = path.read_bytes()
    if len(data) > LIMIT:
        raise SyncError("文件超过本工具大小限制")
    if data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        raise SyncError("第一版不支持 Git LFS：%r" % name)
    entry = {"sha": blob_sha(data), "mode": "100755" if info.st_mode & 0o111 else "100644"}
    return entry, data


def atomic_json(path, value):
    fd, temp = tempfile.mkstemp(prefix=".state-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the Authorization header to another host.
        return None


class GitHub:
    def __init__(self, repo, token=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or any(
                part in (".", "..") for part in repo.split("/")):
            raise SyncError("仓库格式必须是 OWNER/REPO")
        self.prefix = "https://api.github.com/repos/" + repo
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise SyncError("请先在当前终端设置 GITHUB_TOKEN；不要把令牌写入脚本或配置")
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, method, route="", payload=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ghsync/1",
                   "X-GitHub-Api-Version": "2022-11-28", "Authorization": "Bearer " + self.token}
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.prefix + route, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Avoid logging request headers, credentials, or server-echoed payloads.
            raise SyncError("GitHub HTTP %s：检查令牌权限、SSO、分支规则或 API 限额。" % exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise SyncError("API 请求失败：检查网络、HTTPS 代理、证书；写请求不会自动重试。") from None

    def head(self, branch):
        ref = urllib.parse.quote(branch, safe="")
        return self.call("GET", "/git/ref/heads/" + ref)["object"]["sha"]

    def snapshot(self, branch):
        head = self.head(branch)
        tree = self.call("GET", "/git/commits/" + head)["tree"]["sha"]
        files = {}

        def walk(sha, prefix=""):
            result = self.call("GET", "/git/trees/" + sha)
            if result.get("truncated"):
                raise SyncError("目录列表被 API 截断，停止以避免漏文件")
            for item in result["tree"]:
                check_path(item["path"])
                if "/" in item["path"]:
                    raise SyncError("非递归目录响应包含异常路径")
                name = prefix + item["path"]
                check_path(name)
                if item["type"] == "tree":
                    if item["mode"] != "040000":
                        raise SyncError("无效目录模式")
                    walk(item["sha"], name + "/")
                else:
                    files[name] = {"sha": item["sha"], "mode": item["mode"]}

        walk(tree)
        validate_files(files)
        return head, tree, files

    def blob(self, sha):
        response = self.call("GET", "/git/blobs/" + sha)
        if response.get("encoding") != "base64" or response.get("size", LIMIT + 1) > LIMIT:
            raise SyncError("不支持的 Blob 编码或大小（本工具上限 20 MiB）")
        try:
            data = base64.b64decode("".join(response["content"].split()), validate=True)
        except (ValueError, KeyError):
            raise SyncError("Blob 内容损坏") from None
        if blob_sha(data) != sha or len(data) != response["size"]:
            raise SyncError("下载内容校验失败")
        if data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
            raise SyncError("第一版不支持 Git LFS")
        return data

    def publish(self, branch, commit):
        return self.call("PATCH", "/git/refs/heads/" + urllib.parse.quote(branch, safe=""),
                         {"sha": commit, "force": False})


class Workspace:
    def __init__(self, root, api=None):
        self.root = Path(root).expanduser().absolute()
        self.meta = self.root / META
        self.api_override = api

    @contextlib.contextmanager
    def lock(self):
        if not self.root.is_dir() or self.root.is_symlink():
            raise SyncError("工作目录不存在或是符号链接")
        if (self.root / ".git").exists() or (self.root / ".git").is_symlink():
            raise SyncError("请使用独立同步目录，不要在已有 Git 工作区中运行")
        if self.meta.is_symlink():
            raise SyncError("同步记录目录不能是符号链接")
        self.meta.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(str(self.meta / "lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SyncError("另一个同步进程正在运行") from None
            yield

    def state(self):
        path = self.meta / "state.json"
        if path.is_symlink() or not path.is_file():
            raise SyncError("找不到有效同步记录；请先 init 到新目录")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("version") != 1:
            raise SyncError("不支持的同步记录版本")
        validate_files(result["files"])
        for name in result["added"]:
            check_path(name)
        return result

    def save(self, state):
        atomic_json(self.meta / "state.json", state)

    def api(self, state):
        return self.api_override or GitHub(state["repo"])

    def pending_guard(self):
        if (self.meta / "pending.json").exists():
            raise SyncError("存在结果尚未核实的上传。先运行 reconcile，不要重复上传")

    def current(self, state):
        files, data = {}, {}
        for name in sorted(set(state["files"]) | set(state["added"])):
            entry, content = read_file(self.root, name)
            if entry is not None:
                files[name], data[name] = entry, content
        validate_files(files)
        return files, data

    @staticmethod
    def changes(before, after):
        return [("A" if p not in before else "D" if p not in after else "M", p)
                for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]

    def show(self, changes):
        for kind, name in changes:
            print(kind, json.dumps(name, ensure_ascii=False))
        if not changes:
            print("没有需要同步的变更。")

    def init(self, repo, branch=None):
        if self.root.is_symlink():
            raise SyncError("工作目录不能是符号链接")
        if self.root.exists():
            contents = list(self.root.iterdir())
            retry = (len(contents) == 1 and contents[0].name == META and
                     not self.meta.is_symlink() and self.meta.is_dir() and
                     not (self.meta / "state.json").exists() and
                     not (self.meta / "pending.json").exists())
            if contents and not retry:
                raise SyncError("init 仅接受不存在或为空的目录；不会导入或覆盖现有项目")
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock():
            api = self.api_override or GitHub(repo)
            branch = branch or api.call("GET")["default_branch"]
            head, tree, files = api.snapshot(branch)
            state = {"version": 1, "repo": repo, "branch": branch, "base_commit": head,
                     "base_tree": tree, "files": {}, "added": []}
            self.apply_download(state, head, tree, files, api)
            print("初始化完成：%s [%s]，%s 个文件。" % (repo, branch, len(files)))

    def status(self):
        state = self.state()
        files, _ = self.current(state)
        self.show(self.changes(state["files"], files))
        known = set(state["files"]) | set(state["added"])
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                relative = path.relative_to(self.root).as_posix()
                if name not in SKIP and relative not in known:
                    print("?", json.dumps(relative, ensure_ascii=False), "（需 add 才上传）")

    def add(self, names):
        self.pending_guard()
        state = self.state()
        current, _ = self.current(state)
        additions = set(state["added"])
        for name in names:
            check_path(name)
            entry, _ = read_file(self.root, name)
            if entry is None:
                raise SyncError("新增文件不存在：%r" % name)
            current[name] = entry
            if name not in state["files"]:
                additions.add(name)
        validate_files(current)
        state["added"] = sorted(additions)
        self.save(state)
        print("已加入同步；尚未上传。")

    def unadd(self, names):
        self.pending_guard()
        state = self.state()
        for name in names:
            check_path(name)
            if name not in state["added"]:
                raise SyncError("unadd 仅适用于尚未上传的新增文件：%r" % name)
        state["added"] = [name for name in state["added"] if name not in names]
        self.save(state)
        print("已取消新增文件的同步；文件内容保持原样。")

    def upload(self, message, dry_run=False):
        self.pending_guard()
        state = self.state()
        api = self.api(state)
        files, contents = self.current(state)
        changes = self.changes(state["files"], files)
        self.show(changes)
        if api.head(state["branch"]) != state["base_commit"]:
            raise SyncError("远程分支已有更新。本地干净时可 download；若本地也有修改，请 init 到另一个新目录后对照合并")
        # First version refuses file/directory transitions in one upload.
        old_new = set(state["files"]) | set(files)
        for name in old_new:
            parts = name.split("/")
            if any("/".join(parts[:i]) in old_new for i in range(1, len(parts))):
                raise SyncError("请把文件/目录转换拆成删除和新增两次上传")
        if dry_run:
            return
        if not changes:
            if state["added"]:
                self.save(dict(state, added=[]))
            return
        entries = []
        for kind, name in changes:
            if kind == "D":
                entries.append({"path": name, "mode": state["files"][name]["mode"], "type": "blob", "sha": None})
            else:
                result = api.call("POST", "/git/blobs", {"content": base64.b64encode(contents[name]).decode(), "encoding": "base64"})
                if result["sha"] != files[name]["sha"]:
                    raise SyncError("上传 Blob 校验失败；远程分支未更新")
                entries.append(dict(path=name, mode=files[name]["mode"], type="blob", sha=result["sha"]))
        tree = api.call("POST", "/git/trees", {"base_tree": state["base_tree"], "tree": entries})["sha"]
        commit = api.call("POST", "/git/commits", {"message": message, "tree": tree, "parents": [state["base_commit"]]})["sha"]
        new_state = dict(state, base_commit=commit, base_tree=tree, files=files, added=[])
        atomic_json(self.meta / "pending.json", {"old_commit": state["base_commit"], "state": new_state})
        try:
            api.publish(state["branch"], commit)
            if api.head(state["branch"]) != commit:
                raise SyncError("分支结果需要核实")
            self.save(new_state)
            (self.meta / "pending.json").unlink()
        except Exception:
            raise SyncError("上传结果尚未核实；已保留恢复记录，请运行 reconcile。不要直接重复上传") from None
        print("上传完成：" + commit)

    def reconcile(self):
        path = self.meta / "pending.json"
        if not path.exists():
            print("没有待核实的上传。")
            return
        if path.is_symlink():
            raise SyncError("恢复记录不能是符号链接")
        pending = json.loads(path.read_text(encoding="utf-8"))
        old = self.state()
        state = pending["state"]
        validate_files(state["files"])
        if (state["repo"], state["branch"]) != (old["repo"], old["branch"]):
            raise SyncError("恢复记录与工作区不匹配")
        api = self.api(old)
        head = api.head(state["branch"])
        if head == pending["old_commit"]:
            # Retry the same commit, never generate a duplicate commit.
            api.publish(state["branch"], state["base_commit"])
            head = api.head(state["branch"])
        if head != state["base_commit"]:
            compared = api.call("GET", "/compare/" + state["base_commit"] + "..." + head)
            if compared.get("status") != "ahead":
                raise SyncError("远程历史已分叉，保留恢复记录；需要人工合并，禁止强制覆盖")
        self.save(state)
        path.unlink()
        print("上传已核实。可运行 status；远程若又有更新，可在本地干净时 download。")

    def download(self):
        self.pending_guard()
        state = self.state()
        local, _ = self.current(state)
        if self.changes(state["files"], local) or state["added"]:
            raise SyncError("本地有未同步修改/新增。先上传；若远程也更新，请 init 到另一个新目录后对照合并")
        api = self.api(state)
        head, tree, files = api.snapshot(state["branch"])
        self.apply_download(state, head, tree, files, api)
        print("下载完成：" + head)

    def apply_download(self, state, head, tree, files, api):
        validate_files(files)
        changes = self.changes(state["files"], files)
        original = {}
        # Preflight the entire set before downloading or modifying any source files.
        for _, name in changes:
            entry, data = read_file(self.root, name)
            if entry != state["files"].get(name):
                raise SyncError("本地修改或未跟踪文件阻止下载：%r" % name)
            original[name] = (entry, data)
        with tempfile.TemporaryDirectory(dir=str(self.meta), prefix="stage-") as staging:
            staged = {}
            for kind, name in changes:
                if kind != "D":
                    data = api.blob(files[name]["sha"])
                    temp = Path(staging) / str(len(staged))
                    temp.write_bytes(data)
                    staged[name] = temp
            # Editing an unchanged tracked file during download must also stop it.
            local, _ = self.current(state)
            if local != state["files"]:
                raise SyncError("下载期间本地文件发生变化，未应用下载内容")
            for name, (entry, _) in original.items():
                if read_file(self.root, name)[0] != entry:
                    raise SyncError("下载期间本地文件发生变化，未应用下载内容")
            backup = None
            if changes:
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = self.meta / "backups" / stamp
                backup.mkdir(parents=True)
                atomic_json(backup / "manifest.json", {"before": state, "target_commit": head, "changes": changes})
                for name, (entry, data) in original.items():
                    if entry:
                        saved = backup / "files" / name
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        saved.write_bytes(data)
                        saved.chmod(0o755 if entry["mode"] == "100755" else 0o644)
            applied = []
            try:
                for kind, name in changes:
                    path = target(self.root, name)
                    if kind == "D":
                        path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        staged[name].chmod(0o755 if files[name]["mode"] == "100755" else 0o644)
                        os.replace(staged[name], path)
                    applied.append(name)
                self.save(dict(state, base_commit=head, base_tree=tree, files=files, added=[]))
            except Exception:
                for name in reversed(applied):
                    path = target(self.root, name)
                    entry, data = original[name]
                    if entry:
                        path.write_bytes(data)
                        path.chmod(0o755 if entry["mode"] == "100755" else 0o644)
                    else:
                        path.unlink()
                raise
            if backup:
                print("下载前备份：" + str(backup))

    def doctor(self, repo=None, branch=None):
        state = None if repo else self.state()
        api = (self.api_override or GitHub(repo)) if repo else self.api(state)
        info = api.call("GET")
        print("API 连接和仓库读取成功。")
        print("账户仓库写权限提示：", info.get("permissions", {}).get("push", "未提供"))
        if state:
            print("本地基线：", state["base_commit"])
        print("远程分支：", api.head((branch or info["default_branch"]) if repo else state["branch"]))
        print("未执行写请求；令牌写权限和分支规则仍需实际上传验证。")
        if (self.meta / "pending.json").exists():
            print("存在待核实上传：运行 reconcile。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="通过 GitHub REST API 同步独立源码目录，不运行 Git 网络命令")
    parser.add_argument("--directory", default=".", help="独立源码目录，默认当前目录；放在子命令前")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="从远程初始化到空目录；仓库须已有至少一次提交")
    init.add_argument("repo", help="OWNER/REPO")
    init.add_argument("--branch", help="默认使用仓库的默认分支")
    for command in ("status", "download", "reconcile"):
        sub.add_parser(command)
    doctor = sub.add_parser("doctor", help="只读诊断；指定 --repo 时不需要初始化工作区")
    doctor.add_argument("--repo", help="OWNER/REPO")
    doctor.add_argument("--branch")
    add = sub.add_parser("add", help="明确加入新增文件，仅接受文件，不接受目录")
    add.add_argument("paths", nargs="+")
    unadd = sub.add_parser("unadd", help="取消尚未上传的新增文件，不删除文件")
    unadd.add_argument("paths", nargs="+")
    upload = sub.add_parser("upload")
    upload.add_argument("-m", "--message", required=True)
    upload.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    workspace = Workspace(args.directory)
    try:
        if args.command == "init":
            workspace.init(args.repo, args.branch)
        elif args.command == "doctor" and args.repo:
            workspace.doctor(args.repo, args.branch)
        else:
            with workspace.lock():
                if args.command == "add":
                    workspace.add(args.paths)
                elif args.command == "unadd":
                    workspace.unadd(args.paths)
                elif args.command == "upload":
                    workspace.upload(args.message, args.dry_run)
                else:
                    getattr(workspace, args.command)()
        return 0
    except (SyncError, OSError, ValueError, KeyError, RecursionError) as exc:
        print("停止：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

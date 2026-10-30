import base64
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ghsync import GitHub, META, SyncError, Workspace, blob_sha, validate_files


class FakeGitHub(GitHub):
    """In-memory API with immutable objects and fast-forward-only branches."""
    def __init__(self):
        self.blobs, self.trees, self.commits = {}, {}, {}
        self.head_sha = None
        self.calls = []
        self.lose_response = False
        self.race = False
        self.seed({"hello.txt": b"hello\n"})

    def seed(self, contents, modes=None):
        files = {}
        for name, data in contents.items():
            sha = blob_sha(data)
            self.blobs[sha] = data
            files[name] = {"sha": sha, "mode": (modes or {}).get(name, "100644")}
        tree = self.object_sha(files)
        self.trees[tree] = files
        commit = self.object_sha({"tree": tree, "parents": [self.head_sha] if self.head_sha else []})
        self.commits[commit] = {"tree": {"sha": tree}, "parents": [self.head_sha] if self.head_sha else []}
        self.head_sha = commit
        return commit

    @staticmethod
    def object_sha(value):
        return blob_sha(json.dumps(value, sort_keys=True).encode())

    def head(self, branch):
        return self.head_sha

    def snapshot(self, branch):
        tree = self.commits[self.head_sha]["tree"]["sha"]
        files = {name: dict(entry) for name, entry in self.trees[tree].items()}
        validate_files(files)
        return self.head_sha, tree, files

    def call(self, method, route="", payload=None):
        self.calls.append((method, route, payload))
        if method == "GET" and not route:
            return {"default_branch": "main", "permissions": {"push": True}}
        if method == "GET" and route.startswith("/git/blobs/"):
            data = self.blobs[route.rsplit("/", 1)[1]]
            return {"content": base64.b64encode(data).decode(), "encoding": "base64", "size": len(data)}
        if method == "POST" and route == "/git/blobs":
            data = base64.b64decode(payload["content"])
            sha = blob_sha(data)
            self.blobs[sha] = data
            return {"sha": sha}
        if method == "POST" and route == "/git/trees":
            files = {p: dict(e) for p, e in self.trees[payload["base_tree"]].items()}
            for item in payload["tree"]:
                if item["sha"] is None:
                    del files[item["path"]]
                else:
                    files[item["path"]] = {"sha": item["sha"], "mode": item["mode"]}
            tree = self.object_sha(files)
            self.trees[tree] = files
            return {"sha": tree}
        if method == "POST" and route == "/git/commits":
            commit = self.object_sha(payload)
            self.commits[commit] = {"tree": {"sha": payload["tree"]}, "parents": payload["parents"]}
            return {"sha": commit}
        if method == "PATCH":
            assert payload["force"] is False
            if self.race:
                self.race = False
                self.seed({"hello.txt": b"concurrent remote edit"})
            if self.head_sha not in self.commits[payload["sha"]]["parents"]:
                raise SyncError("not fast-forward")
            self.head_sha = payload["sha"]
            if self.lose_response:
                self.lose_response = False
                raise SyncError("timeout after successful branch update")
            return {"object": {"sha": self.head_sha}}
        if method == "GET" and route.startswith("/compare/"):
            base, head = route.split("/compare/")[1].split("...")
            pending = [head]
            while pending:
                item = pending.pop()
                if item == base:
                    return {"status": "ahead"}
                pending.extend(self.commits[item]["parents"])
            return {"status": "diverged"}
        raise AssertionError((method, route, payload))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "work"
        self.api = FakeGitHub()
        self.work = Workspace(self.root, self.api)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.work.init("owner/repo")

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.temp.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_round_trip_binary_deletion_mode_and_noop_upload(self):
        self.write("hello.txt", b"updated\r\n")
        executable = self.write("src/run.sh", b"#!/bin/sh\necho ok\n")
        executable.chmod(0o755)
        self.write("image.bin", b"\x00\xff\r\n")
        self.write("empty", b"")
        self.work.add(["src/run.sh", "image.bin", "empty"])
        self.work.upload("change files")
        state = self.work.state()
        self.assertEqual(state["files"]["src/run.sh"]["mode"], "100755")
        self.assertEqual(self.api.blobs[state["files"]["image.bin"]["sha"]], b"\x00\xff\r\n")
        self.assertEqual(self.api.blobs[state["files"]["empty"]["sha"]], b"")
        self.assertFalse(self.work.changes(state["files"], self.work.current(state)[0]))
        calls = len(self.api.calls)
        self.work.upload("no changes")
        self.assertEqual(calls, len(self.api.calls))
        (self.root / "hello.txt").unlink()
        self.work.upload("delete")
        self.assertNotIn("hello.txt", self.work.state()["files"])

    def test_dry_run_has_no_api_writes_or_state_changes(self):
        self.write("hello.txt", b"new")
        before = self.work.state()
        self.api.calls.clear()
        self.work.upload("preview", True)
        self.assertEqual(before, self.work.state())
        self.assertFalse(any(method != "GET" for method, _, _ in self.api.calls))

    def test_unadded_files_never_uploaded(self):
        self.write("private.env", b"private")
        self.write("hello.txt", b"new")
        self.work.upload("only known files")
        self.assertNotIn("private.env", self.work.state()["files"])

    def test_unadd_keeps_file_and_excludes_it_from_upload(self):
        self.write("new.txt", b"keep locally")
        self.work.add(["new.txt"])
        self.work.unadd(["new.txt"])
        self.work.upload("nothing")
        self.assertEqual((self.root / "new.txt").read_bytes(), b"keep locally")
        self.assertNotIn("new.txt", self.work.state()["files"])

    def test_deleted_staged_addition_can_be_cleared(self):
        self.write("new.txt", b"discard addition")
        self.work.add(["new.txt"])
        (self.root / "new.txt").unlink()
        self.work.upload("nothing")
        self.assertEqual(self.work.state()["added"], [])
        self.work.download()

    def test_remote_update_refuses_upload_before_any_write(self):
        self.write("hello.txt", b"local")
        self.api.seed({"hello.txt": b"remote"})
        self.api.calls.clear()
        with self.assertRaises(SyncError):
            self.work.upload("conflict")
        self.assertFalse(any(method != "GET" for method, _, _ in self.api.calls))
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"local")

    def test_download_refuses_local_modification(self):
        self.write("hello.txt", b"local")
        self.api.seed({"hello.txt": b"remote"})
        with self.assertRaises(SyncError):
            self.work.download()
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"local")

    def test_download_does_not_overwrite_untracked_file(self):
        self.write("new.txt", b"local untracked")
        self.api.seed({"hello.txt": b"hello\n", "new.txt": b"remote"})
        with self.assertRaises(SyncError):
            self.work.download()
        self.assertEqual((self.root / "new.txt").read_bytes(), b"local untracked")

    def test_download_removes_only_tracked_files_and_keeps_backup(self):
        self.write("untracked.txt", b"keep")
        self.api.seed({"new.txt": b"remote"})
        self.work.download()
        self.assertFalse((self.root / "hello.txt").exists())
        self.assertEqual((self.root / "new.txt").read_bytes(), b"remote")
        self.assertEqual((self.root / "untracked.txt").read_bytes(), b"keep")
        saved = list((self.root / META / "backups").glob("*/files/hello.txt"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), b"hello\n")

    def test_download_blob_failure_applies_nothing(self):
        before = self.work.state()
        self.api.seed({"hello.txt": b"new", "new.txt": b"another"})
        original_blob = self.api.blob
        count = 0

        def failing_blob(sha):
            nonlocal count
            count += 1
            if count == 2:
                raise SyncError("offline")
            return original_blob(sha)

        with patch.object(self.api, "blob", side_effect=failing_blob):
            with self.assertRaises(SyncError):
                self.work.download()
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"hello\n")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(before, self.work.state())

    def test_download_rolls_back_if_state_save_fails(self):
        before = self.work.state()
        self.api.seed({"hello.txt": b"new", "new.txt": b"another"})
        with patch.object(self.work, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.work.download()
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"hello\n")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(before, self.work.state())

    def test_download_detects_edit_during_network_request(self):
        self.api.seed({"hello.txt": b"remote"})
        original_blob = self.api.blob

        def editing_blob(sha):
            self.write("hello.txt", b"typed while downloading")
            return original_blob(sha)

        with patch.object(self.api, "blob", side_effect=editing_blob):
            with self.assertRaises(SyncError):
                self.work.download()
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"typed while downloading")

    def test_upload_timeout_reconciles_without_duplicate_commit(self):
        self.write("hello.txt", b"new")
        self.api.lose_response = True
        with self.assertRaises(SyncError):
            self.work.upload("once")
        self.assertTrue((self.work.meta / "pending.json").exists())
        count = len(self.api.commits)
        with self.assertRaises(SyncError):
            self.work.upload("duplicate")
        self.work.reconcile()
        self.assertEqual(len(self.api.commits), count)
        self.assertEqual(self.work.state()["base_commit"], self.api.head_sha)
        self.assertFalse((self.work.meta / "pending.json").exists())

    def test_remote_race_never_forces_branch(self):
        self.write("hello.txt", b"local")
        self.api.race = True
        with self.assertRaises(SyncError):
            self.work.upload("race")
        remote_head = self.api.head_sha
        with self.assertRaises(SyncError):
            self.work.reconcile()
        self.assertEqual(remote_head, self.api.head_sha)
        self.assertTrue((self.work.meta / "pending.json").exists())

    def test_reconcile_retries_same_commit_if_publish_never_arrived(self):
        self.write("hello.txt", b"local")
        with patch.object(self.api, "publish", side_effect=SyncError("offline before request")):
            with self.assertRaises(SyncError):
                self.work.upload("once")
        pending = json.loads((self.work.meta / "pending.json").read_text())
        commit_count = len(self.api.commits)
        self.assertEqual(self.api.head_sha, pending["old_commit"])
        self.work.reconcile()
        self.assertEqual(self.api.head_sha, pending["state"]["base_commit"])
        self.assertEqual(len(self.api.commits), commit_count)

    def test_reconcile_accepts_descendant_without_resetting_remote_head(self):
        self.write("hello.txt", b"local")
        self.api.lose_response = True
        with self.assertRaises(SyncError):
            self.work.upload("once")
        uploaded = self.api.head_sha
        descendant = self.api.seed({"hello.txt": b"remote later"})
        self.work.reconcile()
        self.assertEqual(self.work.state()["base_commit"], uploaded)
        self.assertEqual(self.api.head_sha, descendant)
        self.work.download()
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"remote later")

    def test_download_preserves_binary_and_executable_mode(self):
        self.api.seed({"hello.txt": b"\x00\xff\r\n"}, {"hello.txt": "100755"})
        self.work.download()
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"\x00\xff\r\n")
        self.assertTrue((self.root / "hello.txt").stat().st_mode & 0o111)

    def test_upload_baseline_preserves_edits_made_during_upload(self):
        self.write("hello.txt", b"snapshot")
        original_call = self.api.call

        def call(method, route="", payload=None):
            if method == "POST" and route == "/git/commits":
                self.write("hello.txt", b"newer local edit")
            return original_call(method, route, payload)

        with patch.object(self.api, "call", side_effect=call):
            self.work.upload("snapshot")
        state = self.work.state()
        self.assertEqual(self.work.changes(state["files"], self.work.current(state)[0]), [("M", "hello.txt")])

    def test_symlink_parent_and_leaf_are_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "secret").write_bytes(b"secret")
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SyncError):
            self.work.add(["linked/secret"])
        (self.root / "leaf").symlink_to(outside / "secret")
        with self.assertRaises(SyncError):
            self.work.add(["leaf"])

    def test_traversal_reserved_paths_and_case_collisions(self):
        entry = {"sha": "a" * 40, "mode": "100644"}
        for path in ("../escape", "/absolute", "a//b", "a/./b", ".git/config", "a/.GIT/x", META + "/state.json"):
            with self.subTest(path=path), self.assertRaises(SyncError):
                validate_files({path: entry})
        for files in ({"Readme": entry, "README": entry}, {"A/x": entry, "a/y": entry}):
            with self.assertRaises(SyncError):
                validate_files(files)

    def test_existing_directory_not_adopted(self):
        before = (self.root / "hello.txt").read_bytes()
        with self.assertRaises(SyncError):
            self.work.init("owner/repo")
        self.assertEqual((self.root / "hello.txt").read_bytes(), before)

    def test_nested_lock_refused(self):
        with self.work.lock():
            with self.assertRaises(SyncError):
                with Workspace(self.root, self.api).lock():
                    pass

    def test_corrupt_download_blob_rejected(self):
        sha = blob_sha(b"expected")
        self.api.blobs[sha] = b"wrong"
        with self.assertRaises(SyncError):
            self.api.blob(sha)

    def test_remote_symlink_or_submodule_rejected(self):
        for mode in ("120000", "160000"):
            with self.assertRaises(SyncError):
                validate_files({"special": {"sha": "a" * 40, "mode": mode}})

    def test_doctor_never_probes_write_permission_by_writing(self):
        self.api.calls.clear()
        self.work.doctor()
        self.assertTrue(all(method == "GET" for method, _, _ in self.api.calls))


class SnapshotTests(unittest.TestCase):
    def test_real_snapshot_walks_trees_and_pins_commit(self):
        api = GitHub("owner/repo", "test-token")
        responses = {
            "/git/ref/heads/feature%2Fapi": {"object": {"sha": "c" * 40}},
            "/git/commits/" + "c" * 40: {"tree": {"sha": "d" * 40}},
            "/git/trees/" + "d" * 40: {"tree": [{"path": "src", "type": "tree", "mode": "040000", "sha": "e" * 40}]},
            "/git/trees/" + "e" * 40: {"tree": [{"path": "main.py", "type": "blob", "mode": "100644", "sha": "f" * 40}]},
        }
        with patch.object(api, "call", side_effect=lambda method, route: responses[route]):
            head, tree, files = api.snapshot("feature/api")
        self.assertEqual(head, "c" * 40)
        self.assertEqual(tree, "d" * 40)
        self.assertEqual(files, {"src/main.py": {"sha": "f" * 40, "mode": "100644"}})

    def test_truncated_tree_refused(self):
        api = GitHub("owner/repo", "test-token")
        with patch.object(api, "head", return_value="c" * 40):
            with patch.object(api, "call", side_effect=[{"tree": {"sha": "d" * 40}}, {"truncated": True, "tree": []}]):
                with self.assertRaises(SyncError):
                    api.snapshot("main")


if __name__ == "__main__":
    unittest.main()

# macOS：通过 GitHub API 同步代码

这个工具让公司电脑通过 HTTPS REST API 同步源码，家里电脑继续使用普通 Git。上传和下载都不执行 `git push/pull/fetch`，因此不依赖公司端的 Git 网络通道。使用前应确认目标仓库、API 和代码存储位置获得公司允许。

它同步的是文件，并在远程创建新的 Git 提交；不会复制公司端原有的本地提交历史，也不会自动合并冲突。请在一个独立的新目录里使用，保留原来的项目。工具文件 `ghsync.py` 应放在同步目录外。

## 准备

- macOS，Python 3.9 或更高版本。运行 `python3 --version` 确认；无需安装第三方 Python 包。
- GitHub.com 上已经有至少一次提交的仓库。空仓库可先在网页创建 README。
- GitHub fine-grained personal access token，范围仅选择目标仓库，Repository permissions → **Contents: Read and write**。组织可能还需要审批或 SSO 授权。
- 第一版只支持 `api.github.com`，不支持 GitHub Enterprise 自建 API 地址。

在终端切换到存放 `ghsync.py` 的文件夹。下面的 `OWNER/REPO`、分支和目录是占位示例，需要替换。

在 macOS 默认 zsh 中安全输入令牌，不把令牌本身写进命令历史：

```zsh
read -rs "GITHUB_TOKEN?输入 GitHub Token（不回显）："
export GITHUB_TOKEN
printf '\n'
```

令牌只在当前终端环境中使用，不会写入工具配置或同步目录。新开终端需要重新输入。不要把真实令牌粘贴到聊天中。

## 先做只读诊断

```zsh
python3 ghsync.py doctor --repo OWNER/REPO
```

成功意味着 API 连接、认证和仓库读取正常。该命令不发送写请求，因此不能完全验证令牌的写入范围、组织审批和分支保护规则。网页可访问也不保证 API 可访问。

工具沿用 Python 的 HTTPS 代理和证书配置，保持 TLS 验证。不使用 VPN、隧道，不关闭证书校验。HTTP 重定向会被拒绝，避免将认证头发送到其他地址。

## 初始化独立目录

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" init OWNER/REPO --branch main
```

也可省略 `--branch main`，使用仓库默认分支。指定的分支必须已经存在。若主分支受保护，可先在 GitHub 网页创建一个获准使用的工作分支，然后两端都使用这个工作分支。

初始化会下载远程文件并创建 `.ghsync/` 同步记录。目标目录必须不存在或为空，已有 Git 工作区会被拒绝。初始化失败而只留下 `.ghsync/` 时可以直接重试；如果已经存在源码文件，应保留它们并使用另一个新目录。

如果公司端已有未推送修改：先完成新目录初始化，再用比较工具把原目录的修改对照合并到新目录。不要把旧 `.git/` 或旧 `.ghsync/` 复制进新目录，也不要直接全量覆盖，以免覆盖远程已有修改。

## 公司电脑日常操作

开始工作前，下载家里电脑已推送的变更：

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" download
```

在该目录编辑源码。然后查看差异：

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" status
```

- `M`：已同步文件的内容或可执行权限发生变化。
- `D`：已同步文件被删除；上传会在远程提交这个删除。
- `A`：新文件已明确加入本次同步。
- `?`：未跟踪文件，不会自动上传。

新增文件需要明确加入，路径相对于同步目录，不是相对于当前终端目录：

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" add src/new_file.py assets/logo.png
```

仅接受具体文件路径，不递归加入整个目录。误加入的新增文件可以取消，文件仍保留：

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" unadd assets/logo.png
```

工具不会解释 `.gitignore`；已有远程文件继续受跟踪，新增文件只有 `add` 后才会上传。`status` 默认略过 `.git`、`.ghsync`、`node_modules`、`.venv`、`venv`、`__pycache__` 和 `.DS_Store` 中的未跟踪内容。不要 `add` 本地配置、凭据或构建产物。

先预览，再上传：

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" upload --dry-run -m "更新登录逻辑"
python3 ghsync.py --directory "$HOME/api-work/project" upload -m "更新登录逻辑"
```

预览会检查远程分支，但不发送 API 写请求、不改变同步基线。正式上传会把本次所有已跟踪变更合为一个远程提交；没有变更时不创建空提交。

上传使用 GitHub Blob → Tree → Commit → Reference 接口。以原目录树为基础，仅更新选中的文件，保留其他远程文件；最后一步不允许强制覆盖分支。分支没有更新之前，已上传的对象不会成为分支上的新版本。

## 家里电脑

家里继续正常使用 Git，对同一仓库、同一分支操作：

```zsh
git pull --ff-only
# 修改、测试，然后明确选择要提交的文件
git add src/example.py
git commit -m "在家完成修改"
git push
```

回公司后运行工具的 `download`。尽量按“开始工作先下载，结束工作上传”的顺序交接。

## 冲突与恢复

### 远程更新了，但公司电脑也有修改

工具停止，不会覆盖或自动合并。保留当前目录，执行 `init` 到另一个新目录，例如 `$HOME/api-work/project-merge`，再用比较工具把本地修改对照合并到新目录，然后预览、上传。不要直接把旧目录整体覆盖到新目录。

如果公司端没有未同步修改，直接 `download` 即可。

### 上传后超时，无法判断是否成功

工具会留下 `.ghsync/pending.json`，阻止再次生成提交。网络恢复后执行：

```zsh
python3 ghsync.py --directory "$HOME/api-work/project" reconcile
```

它核实同一个提交是否已经发布；若远程仍在原基线，会重试发布同一个提交，不新建重复提交。若其他提交已在其后追加，会核实祖先关系后更新同步记录。若远程发生分叉，会保留恢复记录并停止，需要人工处理，绝不强制覆盖。

不要删除 `pending.json` 来强行绕过检查。

### 下载失败或需要找回旧文件

下载会先获取并校验全部变更内容，再修改源码。修改前的旧文件及清单保存在 `.ghsync/backups/<时间>/`，普通应用错误会尝试回滚。断电、强制结束进程、磁盘持续故障不保证整批文件原子回滚；可根据备份清单恢复旧文件，并从新目录重新初始化。旧文件的执行权限也记录在清单中。

备份不自动清理，可能占用磁盘空间；确认不再需要时可以自行删除旧备份。不要删除当前 `state.json`。

## 第一版的范围

- 支持普通文本、二进制、空文件、增删改、可执行权限和中文/空格路径；不做换行或 Git clean/smudge 转换。
- 单文件上限为工具自行设置的 **20 MiB**；不是 GitHub 所有接口的统一限额。大型仓库逐目录请求 API，会受速率限制，文件扫描也需要本地内存。
- 不支持 Git LFS、子模块、符号链接、Git hooks 或本地提交签名继承。遇到 LFS 指针、特殊模式、API 目录截断会停止。
- 遇到 macOS 上的大小写或 Unicode 文件名别名冲突会停止。
- 文件与目录互相转换需要分步处理；第一版可能停止这类下载，可初始化到另一个新目录。
- 不支持同时多进程操作同一同步目录。工具锁不能阻止编辑器或其他程序改文件；下载期间检测到改动会停止，但不提供对外部编辑器的完整事务隔离，应用下载时请暂停编辑。
- 分支保护、组织策略、仓库权限和推送保护仍然有效。修改 `.github/workflows/` 可能还需要相应 Workflows 权限；默认不扩大令牌权限。

## 验证

```zsh
python3 -m unittest -v test_ghsync.py
```

测试使用内存中的 GitHub 模拟接口，覆盖完整文件交换、二进制/空文件、删除、执行权限、冲突拒绝、下载前备份、下载失败回滚、并发远程更新和上传结果恢复等行为。没有连接或修改真实 GitHub 仓库；实际 API 连通性和目标仓库规则需在自己的环境验证。

## 官方接口参考

- [Fine-grained token 创建说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Git Database API](https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-your-git-database)
- [Blob](https://docs.github.com/en/rest/git/blobs)、[Tree](https://docs.github.com/en/rest/git/trees)、[Commit](https://docs.github.com/en/rest/git/commits)、[Reference](https://docs.github.com/en/rest/git/refs)

这些接口文档规定了对象创建与非强制更新分支的行为；目录布局、冲突时停止、备份与恢复策略是本工具的实现选择。

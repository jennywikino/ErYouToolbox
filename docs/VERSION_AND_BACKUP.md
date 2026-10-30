# 源码版本与独立数据备份

## 2026-10-29 检查结果

- Git 已初始化，分支 `master`，当前唯一提交 `b85a809`：`Release V0.1 - GameBanana collector`，标签 `v0.1.0`。
- 未配置 remote；有大量 V0.2/V0.3 文件尚未提交，以及 5 个已跟踪文件的修改。
- 现有 31 个已跟踪文件及可达历史中未发现 SQLite、日志、缓存或凭据文件；常见密钥特征检查未发现命中。关键词检查中的 password 为 URL 凭据拒绝逻辑，非实际密码。这不是对所有形式秘密的绝对保证。
- `data/`、`logs/`、数据库和检查点不进入 Git；前端 `node_modules/`、`dist/` 不进入 Git。保留 `frontend/pnpm-lock.yaml`。
- V0.1 标签与历史保持不变。本轮未暂存、提交、添加 remote 或推送。

## 稳定源码提交方案（用户复核后手动执行）

先暂停采集、导入及所有回填任务，完成独立数据备份和测试。源码提交不能代替数据库备份。

```powershell
git switch -c codex/v0.3-stable
git status --short
git diff
git add --dry-run -- .gitignore AGENTS.md README.md V0.1_RELEASE_NOTES.md requirements.txt requirements-ui.txt src scripts tests frontend config docs .streamlit start_toolbox.cmd stop_toolbox.cmd
```

检查 dry-run 文件清单；确认没有私人配置、凭据、数据库和运行数据后，再按同一白名单暂存：

```powershell
git add -- .gitignore AGENTS.md README.md V0.1_RELEASE_NOTES.md requirements.txt requirements-ui.txt src scripts tests frontend config docs .streamlit start_toolbox.cmd stop_toolbox.cmd
git diff --cached --name-only
git diff --cached --check
git diff --cached
git status --short
# 人工确认暂存内容安全且验收通过后：
git commit -m "Release V0.3 - local React browser and safe rating backfill"
git tag v0.3.0
```

若分支或标签已存在，先检查其指向，不重复创建或强制覆盖。不执行 `git add .`。后续提交同样逐个选择功能相关文件。不要把备份目录或清单加入 Git。

## GitHub Private（用户手动操作）

1. 在 GitHub 创建空仓库，选择 **Private**，不要初始化 README、许可证或 .gitignore。
2. 确认没有敏感历史后配置 SSH remote（替换用户名和仓库名，不在 URL 中嵌入令牌）：

```powershell
git remote -v
git remote add origin git@github.com:YOUR_ACCOUNT/ErYouToolbox.git
git remote -v
```

如 origin 已存在，先核对，不覆盖。确认仓库页面确实为 Private、暂存/提交内容安全后，用户再手动执行：

```powershell
git push -u origin codex/v0.3-stable
git push origin v0.3.0
```

Private 不代表可以上传凭据或个人数据库。如以后发现密钥进入历史，应先吊销密钥、评估历史清理方案，停止上传；不要自动重写历史。

## 数据备份与恢复预演

先停止同步、导入和回填任务；React 只读浏览可以保留。SQLite 与 JSON 检查点不是同一事务：备份读取检查点后冻结 SQLite 读取快照，并在完成前检测检查点变化；发现变化会标记失败。暂停写入是取得协调备份的推荐方式。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
$backupDir = Join-Path $env:USERPROFILE 'ErYouToolboxBackups'
& $python scripts/backup_project.py --destination $backupDir
```

目标不依赖移动硬盘盘符。可改成另一块物理磁盘或私人离线备份目录；脚本允许项目外部目标。目标在项目同一卷时会明确警告：这不是独立灾难恢复备份。即使不同卷，也应人工确认不是同一块物理硬盘的另一分区。

每次生成独立时间戳目录，包含 `database.db`、检查点、`manifest.json`。清单只在所有校验及临时恢复通过后标记 `complete`；失败目录保留供排查，不作为可用备份。数据库包含个人状态，备份需放在私人位置。

默认备份：

- `logs/content_ratings/checkpoint_*.json`，包含失败队列。
- `logs/content_ratings/source_pause.json`（如存在）。
- `logs/preview_backfill/*checkpoint*.json`。

自定义位置的检查点需显式添加，例如 `--checkpoint logs/custom/checkpoint.json`；仅接受项目内、已识别格式的 JSON。不要复制 PID、进程锁文件或整个日志目录。

选择具体备份目录进行只读校验和临时恢复：

```powershell
$bundle = Join-Path $backupDir '替换为实际生成的eryoutoolbox_目录名'
& $python scripts/backup_project.py --verify $bundle
```

恢复预演始终写入项目 `data/` 内独立临时目录，检查四张表数量、schema user_version、integrity_check、foreign_key_check 和检查点 SHA-256，结束后清理临时文件。不会覆盖生产数据库；脚本没有直接生产恢复命令。校验清单可发现损坏，不提供恶意篡改的数字签名认证。

## 日常流程

1. 重要修改和批量回填前备份；每日结束及拔出移动硬盘前再备份。
2. 至少一份放在移动硬盘之外；保留多代，定期执行 `--verify`，本工具不自动删除历史备份。
3. 源码验收后单独提交 Git。数据库、检查点靠上述备份保护，不靠 Git。
4. 跨电脑时在各自 `%LOCALAPPDATA%\ErYouToolbox\venv` 初始化环境，不复制虚拟环境；启动路径由脚本定位。
5. 真正恢复前关闭所有写入任务，保留当前数据库和检查点副本，确认目标路径后另行制定恢复操作，不直接覆盖。

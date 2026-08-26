# scripts/

运维与启动脚本：

- M12：`download_models.md`（Will 手动下载模型权重的指引）、`smoke_real_models.sh`
- M13：`mac_install.sh`、`backup.sh`、`restore.sh`、`launchd/`

M12 的模型权重由 Will 按 `download_models.md` 手动准备；代码和脚本都不会下载权重。

## Mac Mini 首次安装

在仓库根目录执行：

```bash
./scripts/mac_install.sh
./scripts/launchd/install_launchd.sh
```

安装脚本要求 macOS 与 Python 3.12；缺 Python 时会使用已有的 Homebrew 安装
`python@3.12`。它会创建 `.venv`、安装 Python 依赖、执行 Alembic 迁移，随后安装并
构建前端。launchd 服务只监听 `127.0.0.1:8000`，API 与 `apps/web/dist` 由同一个
uvicorn 进程提供。可先用 `DRY_RUN=1` 查看两个安装脚本将执行的动作。

## 备份与恢复

```bash
./scripts/backup.sh
./scripts/restore.sh backups/meeting-workbench-YYYYmmdd-HHMMSS.tar.gz /新的/data/目录
```

备份默认读取仓库的 `data/` 并写入 `backups/`。可用 `MW_DATA_DIR` 与
`BACKUP_ROOT` 改写这两个位置。归档包含 SQLite 和会议数据，但始终排除
`data/models/` 下的模型权重（包括 `.onnx`、`.safetensors`）。恢复只接受一个尚不
存在的新目录，成功后可把 `MW_DATA_DIR` 指向该目录再启动服务。

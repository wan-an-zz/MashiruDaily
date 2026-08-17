# AGENTS.md — MashiruDaily.Server（Python 后端）

> 本目录是独立的 Python FastAPI 项目，**不在 `MashiruDaily.slnx` 里**，有自己的 `.venv` 与 pytest 套件。运维细节以 `README.md`（运维手册）为准，本文件只钉代理必须遵守的纪律。改动契约相关代码前先读 `docs/design/通信协议.md`。

## 概览

两职责：① **拉取服务器**（只读 GET，默认 `0.0.0.0:8123`：`/health`、`/api/todo/meta`、`/api/todo`，数据源 `data/todo.json`）；② **Hermes 装配工具集**（`bootstrap.py` 一键串联 setup_server → register_skills → configure_webhook → configure_cron → install_autostart）。开发采用 **TDD**：先写契约测试（RED）再实现转绿。

## WHERE TO LOOK

| 路径 | 内容 |
|---|---|
| `app/` | `main.py`（FastAPI 入口+端点）、`todo_store.py`（纯数据读写，无 HTTP）、`config.py`（环境变量驱动配置） |
| `hermes_plugin/mashiru_daily/` | Hermes 插件：`tools.py`（todo_* 工具实现，原子写）、`schemas.py`（LLM Schema，钉了 HasSynced/createdAt 禁令）、`plugin.yaml` |
| `tools/test_webhook_signed.py` | 签名 webhook 冒烟（唯一联网测试，**不在 pytest 套件内**） |
| `tests/` | 52 个离线契约测试（test_api 9 / test_hermes_plugin 7 / test_bootstrap 23 / test_configure_webhook 11 / test_install_autostart 2） |
| 根目录脚本 | `setup_server.py`、`register_skills.py`、`configure_webhook.py`、`configure_cron.py`、`install_autostart.py`、`bootstrap.py`、`_config.py`（共享工具） |

## 命令

```bash
pytest MashiruDaily.Server/tests -v     # 完全离线
.venv\Scripts\python.exe -m app.main    # 手动启动（Windows）
```

## 纪律（违反 = 协议破坏或安全事故）

- **`createdAt` 只在 `todo_meta_stamp` 运行时改变**（仅两处：`setup_server.py` 首次引导、每日 cron 结束）。webhook 驱动的 `todo.json` 修改**禁止**碰侧车，否则客户端每次同步都误判「需要拉取」。
- **`HasSynced` 禁止出现**：`data/todo.json` 不含它，工具校验拒绝写入，Schema 文档明令禁止。
- **密钥纪律**：来自 `--secret` 或 `MASHIRU_WEBHOOK_SECRET`，禁硬编码/交互/进命令行/打印（打印前深拷贝 + 掩码 `***`）。`bootstrap.py` 经环境变量注入子进程。
- **配置走环境变量**（`MASHIRU_DATA_DIR`/`MASHIRU_HOST`/`MASHIRU_PORT`/`HERMES_HOME`），路径相对 `SERVER_ROOT` 解析，**绝不用 `os.getcwd()`**（cron/systemd 启动时 cwd 不可信）。
- **幂等可重跑**：全部装配脚本；改 `config.yaml` 前备份 `config.yaml.bak-<时间戳>`；`register_skills.py` 遇已存在插件目录绝不覆盖；cron 任务名判断要求词边界。
- **原子写**：`tools.py` 与 `todo_store.py` 一律先写 `.tmp` 再 `os.replace`。
- **数据形状**：`todo.json` 顶层必须是数组、侧车键完整，否则统一 `ValueError` → 500 JSON `detail`（不许 KeyError 裸崩）。
- **错误以 JSON 字符串返回**：`hermes_plugin` 的 handler 绝不向上抛异常。
- 时间戳 ISO8601 以 `Z` 结尾（与 C# 端 AssumeUniversal 解析兼容）。

## ANTI-PATTERNS（代码注释里钉死的坑）

- 判定 Hermes 网关降级信号时只匹配单条输出流 — 两信号可能分落 `stderr`/`stdout`，**必须合并匹配**。
- crontab 匹配先匹配短的启用标记 — 禁用标记是启用标记的子串，**先匹配更长的禁用标记**。
- subprocess 解码不带 `errors="replace"` — 中文输出会炸崩溃。
- `install_autostart.py` 的 `/RU SYSTEM` 任务 cwd 是 system32 — 必须显式 cd 才能 `python -m app`。
- 把联网测试塞进 pytest 套件 — 套件必须完全离线（用 in-process `TestClient` + monkeypatch 环境变量 + `_no_real_io` 兜底）。

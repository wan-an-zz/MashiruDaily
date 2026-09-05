# AGENTS.md — MashiruDaily.Server（Python 后端）

> 本目录是独立的 Python FastAPI 项目，**不在 `MashiruDaily.slnx` 里**，有自己的 `.venv` 与 pytest 套件。运维细节以 `README.md`（运维手册）为准，本文件只钉代理必须遵守的纪律。改动契约相关代码前先读 `docs/api&webhooks/通信协议.md`（当前链路：`POST /api/update` 改写数据，Hermes Webhook 只用于触发 Agent 反应）。

## 概览

三职责：① **拉取服务器**（默认 `0.0.0.0:8123`：`GET /health`、`GET /api/todo/meta`、`GET /api/todo`、`GET /api/messages`，数据源 `$HOME/.mashiru-daily/todos/todo.json`）；② **事件接收**（`POST /api/update`，客户端 HMAC 签名批量推送，直接复用 `hermes_plugin` 的 `todo_upsert`/`todo_delete` 改写 `todo.json`，返回 `{success, error_ids, success_ids}`）；③ **Hermes 装配工具集**（`bootstrap.py` 一键串联 setup_server → register_hermes_plugin → configure_webhook → configure_cron → install_autostart）。开发采用 **TDD**：先写契约测试（RED）再实现转绿。

## WHERE TO LOOK

| 路径 | 内容 |
|---|---|
| `app/` | `main.py`（FastAPI 入口+端点，含 `POST /api/update`、`GET /api/messages`）、`funcs.py`（纯数据读写，无 HTTP）、`config.py`（环境变量驱动配置） |
| `hermes_plugin/mashiru_daily/` | Hermes 插件：`tools.py`（todo_* 工具实现，原子写）、`schemas.py`（LLM Schema，钉了 has_synced/created_at 禁令）、`plugin.yaml`、`skills/`（4 个 skill：daily-planning/stage-goal-planning/todo-assigning/todo-updating-and-observation，目录名=skill 名） |
| `tests/` | 离线契约测试（test_api / test_hermes_plugin / test_bootstrap / test_configure_webhook / test_install_autostart / test_uninstall / test_data_dir_default） |
| 根目录脚本 | `setup_server.py`、`register_hermes_plugin.py`、`configure_webhook.py`、`configure_cron.py`、`install_autostart.py`、`bootstrap.py`、`_config.py`（共享工具） |

## 命令

```bash
pytest MashiruDaily.Server/tests -v     # 完全离线；无 pytest 配置，纯默认发现
.venv\Scripts\python.exe -m app.main    # 手动启动（Windows）
```

## 纪律（违反 = 协议破坏或安全事故）

- **`todo-meta.json` 的 `updated_at` 维护**：Hermes 侧仅在 `todo_meta_stamp` 运行时刷新（`setup_server.py` 首次引导、每日 cron 结束）；`/api/update` 推送驱动 `todo.json` 修改时，服务端必须用请求体携带的 `updated_at` 刷新侧车；客户端成功推送后同步推进本地 `LastSyncedAt`，避免把自己的推送误判为需要拉取。
- **`has_synced` 禁止出现**：`$HOME/.mashiru-daily/todos/todo.json` 不含它，工具校验拒绝写入，Schema 文档明令禁止。
- **密钥纪律**：来自 `--secret` 或 `MASHIRU_WEBHOOK_SECRET`，禁硬编码/交互/进命令行/打印（打印前深拷贝 + 掩码 `***`）。`bootstrap.py` 经环境变量注入子进程。
- **配置走环境变量**（`MASHIRU_DATA_DIR`/`MASHIRU_HOST`/`MASHIRU_PORT`/`HERMES_HOME`），默认数据目录为 `$HOME/.mashiru-daily/todos`（可用 `MASHIRU_DATA_DIR` 覆盖），路径**绝不用 `os.getcwd()`**（cron/systemd 启动时 cwd 不可信）。
- **幂等可重跑**：全部装配脚本；改 `config.yaml` 前备份 `config.yaml.bak-<时间戳>`；`register_hermes_plugin.py` 遇已存在插件目录绝不覆盖；cron 任务名判断要求词边界。
- **原子写**：`tools.py` 与 `funcs.py` 一律先写 `.tmp` 再 `os.replace`。
- **数据形状**：`todo.json` 顶层必须是数组、侧车键完整，否则统一 `ValueError` → 500 JSON `detail`（不许 KeyError 裸崩）。
- **错误以 JSON 字符串返回**：`hermes_plugin` 的 handler 绝不向上抛异常。
- 时间戳统一为 ISO8601 UTC+8，带 `+08:00` 偏移（与 C# 端解析兼容）。
- **模块依赖方向**：`app/main.py` 反向 import `hermes_plugin.mashiru_daily.tools`（复用 todo_upsert/todo_delete）—— 改工具签名时两端都要动。

## ANTI-PATTERNS（代码注释里钉死的坑）

- 判定 Hermes 网关降级信号时只匹配单条输出流 — 两信号可能分落 `stderr`/`stdout`，**必须合并匹配**。
- crontab 匹配先匹配短的启用标记 — 禁用标记是启用标记的子串，**先匹配更长的禁用标记**。
- subprocess 解码不带 `errors="replace"` — 中文输出会炸崩溃。
- `install_autostart.py` 的 `/RU SYSTEM` 任务 cwd 是 system32 — 必须显式 cd 才能 `python -m app`；且 SYSTEM/root 的 `$HOME` 不是安装者 `$HOME` — 注册自启时**必须把安装者数据目录固化进 `MASHIRU_DATA_DIR`**，否则 FastAPI 与 Hermes 各读一份 todo.json。
- 把联网测试塞进 pytest 套件 — 套件必须完全离线（用 in-process `TestClient` + monkeypatch 环境变量 + `_no_real_io` 兜底）。
- `configure_webhook.py` 直接修改 config 活数据 — 改前必须深拷贝，且只合并 webhook 平台、**绝不触碰其它平台配置**。

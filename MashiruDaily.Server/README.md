# MashiruDaily.Server 运维手册

> 本文档是 MashiruDaily.Server（Python 后端）的运维手册。仓库采取测试先行（TDD）开发：先写契约测试（RED），再实现 `app/main.py` 转绿。当前 `pytest MashiruDaily.Server/tests -v` 7 个用例全部通过。

## 1. 项目概览

MashiruDaily.Server 是一个轻量 Python 后端，承担两个职责：一是**拉取服务器**，以 FastAPI 提供两个只读 GET 端点，供 MashiruDaily 客户端（Avalonia 桌面 / Android / TUI）上线时拉取权威当日待办列表；二是**Hermes 装配工具集**，一键把本机安装的 Hermes Agent 配置为可接收 webhook、每日维护 todo.json 的智能体（示例 skill、每日 cron、物理开机自启）。

数据位于 `data/`：`todo.json`（PascalCase 字段）是服务器侧唯一数据源，`todo-meta.json` 是侧车文件，专为客户端拉取决策记录 `createdAt`。服务器对数据只读，真正的写者是 Hermes Agent（每日 cron 例行更新 + webhook 事件即时更新）。

同步拓扑（权威契约见 `docs/design/通信协议.md`）：

- 客户端 → Hermes：带 HMAC-SHA256 签名的 webhook POST，地址 `http://<主机>:8644/webhooks/todo-sync`，由 Hermes 内置网关处理，据此更新 `todo.json`。
- 客户端 → 本服务器：`GET /api/todo/meta` 与 `GET /api/todo`，只读，不修改任何服务器状态。

## 2. 目录结构

```
MashiruDaily.Server/
├── app/                     FastAPI 应用
│   ├── config.py            运行设置，由环境变量 MASHIRU_DATA_DIR / MASHIRU_HOST / MASHIRU_PORT / HERMES_HOME 驱动
│   ├── todo_store.py        todo.json 与 todo-meta.json 的纯读取/初始化函数（无 HTTP 层）
│   └── main.py              FastAPI 入口与 GET 端点（`python -m app.main`）
├── hermes_plugin/           Hermes 插件集合目录
│   ├── __init__.py          集合包说明
│   └── mashiru_daily/       Hermes 插件源目录（工具 + skill，manifest 名 mashiru-daily）
│       ├── plugin.yaml      Hermes 插件清单
│       ├── __init__.py      register(ctx)：注册 todo_* 工具与内置 skill
│       ├── schemas.py       todo_* 工具的 LLM Schema
│       ├── tools.py         todo.json / todo-meta.json 读写实现（原子写）
│       └── skills/
│           └── mashiru-todo/ 插件内置 skill（SKILL.md），指导 Hermes 使用 todo_* 工具
├── tools/
│   ├── stamp_todo_meta.py   每日戳记脚本，等价于 todo_meta_stamp 工具
│   └── test_webhook_signed.py  签名 webhook 冒烟测试（模拟客户端推送，含 --negative 负例）
├── skills/                  （旧目录，已迁移至 hermes_plugin/mashiru_daily/skills，保留仅为兼容）
├── tests/
│   ├── test_api.py          GET 端点契约的 pytest 集成测试（离线）
│   ├── test_hermes_plugin.py  hermes_plugin todo_* 工具离线测试
│   └── ...
├── setup_server.py          一次性初始化：创建 .venv、安装依赖、初始化 data/、盖章初始 meta（幂等）
├── register_skills.py       安装/链接 hermes_plugin 到 Hermes 并启用插件，注册外部 skill 目录（幂等）
├── configure_webhook.py     配置 Hermes webhook 平台与 todo-sync 路由（幂等，需密钥）
├── configure_cron.py        创建每日 Hermes cron 任务 mashiru-daily（幂等）
├── install_autostart.py     物理开机自启（Windows: schtasks ONSTART；Linux/macOS: systemd 系统服务/crontab）
├── bootstrap.py             一键初始化：串联全部开始流程（推荐入口）
├── _config.py               共享工具：定位 hermes、备份 config.yaml、round-trip 读写
└── requirements.txt         fastapi / uvicorn / ruamel.yaml / pytest / httpx
```

## 3. 快速开始

**一键初始化（推荐）**：`bootstrap.py` 一条命令按序串联全部开始流程：setup_server → register_skills → configure_webhook → configure_cron → install_autostart → 启动验证。任一环节失败立即停止（fail-fast）；各子脚本均幂等，可重复运行。用系统 Python 运行，纯标准库，无第三方依赖（与 `setup_server.py` 同款）：

```powershell
python bootstrap.py --secret <密钥>
```

密钥经环境变量注入各子脚本，不会显示在命令行回显中；也可改用环境变量 `MASHIRU_WEBHOOK_SECRET` 提供。

可选参数：

| 参数 | 说明 |
|---|---|
| `--venv <目录名>` | 虚拟环境名，默认 `.venv` |
| `--secret <密钥>` | webhook 密钥；也可用环境变量 `MASHIRU_WEBHOOK_SECRET` |
| `--skip-setup` / `--skip-skills` / `--skip-webhook` / `--skip-cron` / `--skip-autostart` | 跳过对应步骤 |
| `--no-verify` | 跳过末尾的启动验证 |
| `--no-restart` | 透传 configure_webhook（不自动重启网关） |
| `--schedule <表达式>` | 透传 configure_cron，默认 `0 9 * * *` |
| `--dry-run` | 演练：只打印将执行的命令，不实际执行 |

> ⚠️ **注意事项**
>
> - **install_autostart 步骤**：Windows 会弹 UAC 提权，Linux 需要 sudo（详见第 5 节）。
> - **末尾验证步骤**：会短暂启动服务器，请求 `/health` 与 `/api/todo/meta` 后自动关闭。

**第一步：初始化**（前置条件：已装 Python 3 与本机 Hermes Agent。用系统 Python 运行，脚本只用标准库，无第三方依赖）：

```powershell
python setup_server.py
```

脚本依次完成四件事：创建虚拟环境 `.venv`（已存在则跳过）、用 `.venv` 的 pip 安装 `requirements.txt`、创建 `data/`、运行 `tools/stamp_todo_meta.py` 生成初始侧车。可加 `--venv <目录名>` 自定义虚拟环境名。幂等可重复运行，若检测到已在虚拟环境中会给出警告。

**第二步：启动拉取服务器**：

```powershell
.venv\Scripts\python.exe -m app.main
```

也可用 `install_autostart.py` 注册**物理开机自启**（系统启动即运行、无需登录；Windows 用 schtasks ONSTART + SYSTEM，Linux/macOS 用 systemd 系统服务或 crontab @reboot），见第 5 节。

**第三步：验证**：

```powershell
curl http://localhost:8123/health
curl http://localhost:8123/api/todo/meta
curl http://localhost:8123/api/todo
```

`/health` 返回存活状态；`/api/todo/meta` 返回 `{date, createdAt, count}`；`/api/todo` 返回 PascalCase 待办数组。Windows PowerShell 中 `curl` 是 Invoke-WebRequest 别名，装了 curl.exe 可改用 `curl.exe`。默认监听 `0.0.0.0:8123`，可用环境变量 `MASHIRU_HOST` / `MASHIRU_PORT` / `MASHIRU_DATA_DIR` 覆盖。

**第四步：装配 Hermes**，按第 5 节顺序执行 register_skills → configure_webhook → configure_cron。

## 4. 客户端设置对照表（重要）

在 MashiruDaily 客户端设置页填写以下值（契约见 `docs/design/通信协议.md`）：

| 客户端设置项 | 值 | 说明 |
|---|---|---|
| `ServerBaseUrl` | `http://<主机>:8123` | 拉取服务器（本服务器） |
| `HermesBaseUrl` | `http://<主机>:8644` | Hermes webhook 网关 |
| `WebhookRouteName` | `todo-sync` | 拼成 `POST http://<主机>:8644/webhooks/todo-sync` |
| `WebhookSecret` | 与第 5 节 `configure_webhook.py --secret` 的值一致 | HMAC-SHA256 签名密钥 |

`<主机>` 为本机局域网地址（如 `192.168.1.100`）。Android 客户端经局域网访问，所以服务器必须监听 `0.0.0.0`（默认即是）。注意 `ServerBaseUrl` 在客户端默认与 `HermesBaseUrl` 相同（8644），因拉取服务器独立在 8123，须手动改为 `http://<主机>:8123`。客户端数据落盘于 `%APPDATA%\MashiruDaily\`（`todos.json` + `settings.json`）。

## 5. 配置脚本用法

四个脚本全部幂等，重复运行不产生改动。其中直接修改 `HERMES_HOME/config.yaml` 的两个（register_skills、configure_webhook）**只在真正修改前**备份为 `config.yaml.bak-<时间戳>`；configure_cron 走 `hermes cron` 命令、install_autostart 走注册表/systemd/crontab，不触碰 config.yaml。统一用 `.venv` 内的 Python 运行（改 config.yaml 的两个依赖 ruamel.yaml，必须如此）。Hermes 与 config.yaml 的定位：默认 `%LOCALAPPDATA%\hermes`，可用环境变量 `HERMES_HOME` 覆盖。

**register_skills.py**：把 `hermes_plugin/mashiru_daily/` 以目录链接安装到 `$HERMES_HOME/plugins/mashiru-daily`，通过 Hermes CLI（`hermes plugins enable`）启用插件；同时把 `hermes_plugin/mashiru_daily/skills` 写入 config.yaml 的 `skills.external_dirs`（不存在则创建，已包含则跳过，并迁移移除旧 `Server/skills` 引用）。插件内的 `register(ctx)` 负责通过 Hermes 接口注册全部 `todo_*` 工具与内置 skill：

```powershell
.venv\Scripts\python.exe register_skills.py
```

**configure_webhook.py**：合并 `platforms.webhook = {enabled, extra:{port: 8644, routes:{todo-sync:{...}}}}` 到 config.yaml。其它平台（如 qqbot）与既有路由一律保留，只覆盖 todo-sync。写入后校验，默认执行 `hermes gateway restart`（webhook 变更需重启生效，网关连接会短暂断开）。不想自动重启、只打印命令时加 `--no-restart`：

```powershell
.venv\Scripts\python.exe configure_webhook.py --secret <密钥>
.venv\Scripts\python.exe configure_webhook.py --secret <密钥> --no-restart
```

密钥必须来自 `--secret` 参数或环境变量 `MASHIRU_WEBHOOK_SECRET`（二选一必填），脚本拒绝硬编码与交互输入。**密钥是运行时秘密，禁止写进代码、config.yaml 或任何提交内容**：

```powershell
$env:MASHIRU_WEBHOOK_SECRET = "<密钥>"
.venv\Scripts\python.exe configure_webhook.py
```

**configure_cron.py**：创建每日 Hermes cron 任务 `mashiru-daily`（默认每日 09:00，表达式 `0 9 * * *`）。提示词要求 Hermes 使用 `todo_*` 工具检查并更新 `data/todo.json` 与 `data/plan.md`，每次运行结束时调用 `todo_meta_stamp` 刷新 createdAt；创建命令附带 `--skill mashiru-todo`。已存在则跳过。可选 `--name`、`--schedule`、`--workdir`：

```powershell
.venv\Scripts\python.exe configure_cron.py
.venv\Scripts\python.exe configure_cron.py --schedule "0 9 * * *"
```

**install_autostart.py**：注册**物理开机自启**（系统启动即运行、不依赖登录；幂等）。Windows 用 `schtasks /SC ONSTART /RU SYSTEM`（系统启动即触发、SYSTEM 账户无需登录免密码）；Linux/macOS 优先 **systemd 系统服务**（`/etc/systemd/system/mashirudaily-server.service`，`WantedBy=multi-user.target`，物理开机自启 + 崩溃自动重启 + 网络就绪后启动）；无 systemd 时回退 **crontab `@reboot`**（cron 守护进程开机即执行，无需登录、**免 sudo**，但无崩溃自动重启与依赖排序）。四个参数互斥，`--dry-run` 只打印将执行的命令：

> ⚠️ **权限要求（务必注意）**
>
> - **Linux：必须 sudo。** 写 `/etc/systemd/system` 单元文件、`systemctl enable/disable` 都是系统级操作。脚本在**非 root** 下运行时会自动给每个命令加 `sudo` 前缀（会提示输入密码）；也可直接以 `sudo .venv/bin/python install_autostart.py` 运行。当前用户无 sudo 权限时脚本拒绝执行并提示改用 crontab。
> - **Windows：必须管理员。** `schtasks /SC ONSTART /RU SYSTEM` 需要提权；脚本在非管理员下运行会自动弹 UAC 提权重启自身。
> - 唯一的免 sudo/免管理员替代是 crontab `@reboot`（仅当 Linux 无 systemd 时自动回退，或手动改用）。
>
> 注意区分：注册表 `HKCU\...\Run` 与 systemd **用户**服务（`systemctl --user`）都是**登录后**启动，不满足物理开机需求，故本脚本不采用。

```powershell
# Windows（非管理员时自动弹 UAC 提权）
.venv\Scripts\python.exe install_autostart.py              # 注册物理开机自启
.venv\Scripts\python.exe install_autostart.py --disable    # 临时禁用（不删除）
.venv\Scripts\python.exe install_autostart.py --enable     # 重新启用
.venv\Scripts\python.exe install_autostart.py --uninstall  # 删除自启
.venv\Scripts\python.exe install_autostart.py --dry-run    # 演练：只打印命令不执行
```

```bash
# Linux（需 sudo；非 root 运行会自动加 sudo 前缀）
sudo .venv/bin/python install_autostart.py                 # 注册物理开机自启
sudo .venv/bin/python install_autostart.py --disable       # 临时禁用（不删除）
sudo .venv/bin/python install_autostart.py --enable        # 重新启用
sudo .venv/bin/python install_autostart.py --uninstall     # 删除自启
.venv/bin/python install_autostart.py --dry-run            # 演练：只打印命令不执行（无需 sudo）
```

## 6. createdAt 语义（重要）

`todo-meta.json` 的 `createdAt` 是客户端判定「是否需要拉取」的主字段（协议 5.1、5.3）：

- `createdAt` **只在 `tools/stamp_todo_meta.py` 或 Hermes 插件工具 `todo_meta_stamp` 运行时改变**。运行时机仅两处：`setup_server.py` 首次引导，以及每日 cron agent 每次运行结束时（configure_cron.py 的提示词已内建该步骤）。
- **webhook 驱动的 `todo.json` 修改绝不改变 `createdAt`**。Hermes 收到 webhook 后应使用 `todo_*` 工具更新 `todo.json`，但**禁止调用 `todo_meta_stamp`**，也不要直接编辑侧车。否则客户端每次 webhook 同步后都会因时间戳更新而误判「需要拉取」，造成无谓的全量拉取。
- `count` 始终是实时值：`GET /api/todo/meta` 返回前取 `len(todo.json)`，侧车里的旧 count 不参与。

## 7. 数据文件

**`data/todo.json`**：PascalCase，与客户端本地 `todos.json` 字段完全一致，**不含 `HasSynced`**（客户端本地字段，禁止传输）：

```json
[
  {
    "Id": "22222222-2222-2222-2222-222222222222",
    "Title": "买菜",
    "IsCompleted": true,
    "CreatedAt": "2026-08-10T09:00:00+08:00",
    "CompletedAt": "2026-08-10T11:30:00+08:00"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `Id` | string (GUID) | 条目唯一标识 |
| `Title` | string | 标题 |
| `IsCompleted` | bool | 是否已完成 |
| `CreatedAt` | string (ISO 8601) | 创建时间 |
| `CompletedAt` | string (ISO 8601) 或 null | 完成时间，未完成时为 null |

**`data/todo-meta.json`**：恰好三个字段：

```json
{ "date": "2026-08-10", "createdAt": "2026-08-10T09:00:00Z", "count": 12 }
```

`date` 为当日日期（yyyy-MM-dd，兼容保留）；`createdAt` 为 ISO 8601 UTC（Z 结尾，兼容 C# 端 AssumeUniversal 解析）；`count` 为实时条数。

**`data/plan.md`**：每日计划，由 Hermes Agent 维护。边界行为：`todo.json` 缺失时 `GET /api/todo` 返回空数组，非法 JSON 返回 500；侧车缺失时首次请求 meta 自动创建。

## 8. 测试

仓库根目录运行（完全离线，无网络请求）：

```powershell
pytest MashiruDaily.Server/tests -v
```

覆盖：meta 结构合法、`GET /api/todo` 逐字回显 PascalCase 且无 `HasSynced`、空目录返回空数组、首次请求自动建侧车、非法 JSON 返回 500、webhook 式编辑不改 createdAt 而 stamp 会改、count 实时反映条数，以及 `hermes_plugin` 的 `todo_*` 工具读写/upsert/delete/stamp 行为。已全部通过。

另可运行 `tools/test_webhook_signed.py` 做端到端冒烟：向 Hermes 网关 `:8644/webhooks/todo-sync` 发送签名事件（`--secret` 必填），2xx 即成功；`--negative` 用错误密钥验证网关返回 401。

## 9. 端口

| 端口 | 用途 | 说明 |
|---|---|---|
| 8123 | 拉取服务器（FastAPI） | 默认监听 `0.0.0.0`，局域网客户端可访问；用 `MASHIRU_PORT` 覆盖 |
| 8644 | Hermes webhook 网关 | 客户端 `POST /webhooks/todo-sync` 的目标；由 Hermes 配置，见第 5 节 |

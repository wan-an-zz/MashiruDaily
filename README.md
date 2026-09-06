# MashiruDaily

> 面向初、高中学生的 Hermes Agent 驱动 Todo List 项目。
> 客户端负责呈现和管理每日学习计划，后端由 Hermes Agent 作为“规划者”每天生成计划，并通过事件推送与 Webhook 让两端保持同步。

MashiruDaily 由三部分组成：

- **桌面端 / TUI 客户端**：.NET 10 + Avalonia / Terminal.Gui，负责展示与编辑 Todo。
- **MashiruDaily.Server**：Python FastAPI 自部署后端，负责存放 Todo 数据、接收客户端推送、向客户端提供 Agent 消息。
- **Hermes Agent 集成**：服务端内置 Hermes 插件与 4 个 skill，可每日生成学习计划、分配任务并对客户端的变更做出反应。

---

## 目录

- [项目特色](#项目特色)
- [技术栈](#技术栈)
- [仓库结构](#仓库结构)
- [架构与数据流](#架构与数据流)
- [快速开始](#快速开始)
- [客户端设置](#客户端设置)
- [服务端 API](#服务端-api)
- [数据文件](#数据文件)
- [测试](#测试)
- [打包与发布](#打包与发布)
- [开发说明](#开发说明)
- [常见问题](#常见问题)

---

## 项目特色

- **Hermes 每日规划**：后端 Hermes Agent 按 cron 定时制定当日学习计划，写入 `todo.json`。
- **多端共享数据**：桌面端、TUI 和移动/浏览器端（实验性）共享同一个 Core 领域层与同一个后端数据源。
- **本地优先**：客户端 Todo 保存在本地 JSON，离线也能使用，联网后再同步。
- **可靠同步**：
  - 启动时通过 `updated_at` 判断是否需要拉取；
  - 本地修改通过批量事件 `POST /api/update` 推送；
  - 推送成功后通过 Hermes Webhook 触发 Agent 反应；
  - 支持失败重试、429 退避、部分成功与 `error_ids`/`success_ids` 解析。
- **事件驱动**：客户端事件类型统一为 `todo_added` / `todo_updated` / `todo_completed` / `todo_reopened` / `todo_deleted`。
- **防回环设计**：拉取覆盖时抑制本地 `Changed` 事件；`MarkSyncedAsync` 不触发变更事件，避免多端同步出现回声/死循环。
- **自部署服务端**：一键脚本可完成 `.venv` 创建、Hermes 插件注册、Webhook 配置、cron 安装与开机自启。
- **终端可用**：TUI 基于 Terminal.Gui v2，适合树莓派等无桌面环境使用。

---

## 技术栈

| 端 | 技术 |
|---|---|
| 共享领域层 | .NET 10、CommunityToolkit.Mvvm、NLog |
| 桌面端 | Avalonia 12.1、SukiUI、MVVM + DI |
| TUI | Terminal.Gui v2（.NET 10 控制台） |
| 移动/浏览器（实验性） | Avalonia Android / Browser / iOS |
| 服务端 | Python、FastAPI、Uvicorn、ruamel.yaml |
| Hermes 插件 | `hermes_plugin/mashiru_daily`，内置 4 个 skill |
| 测试 | xUnit（.NET）、pytest（Python） |

---

## 仓库结构

```text
MashiruDaily/
├── MashiruDaily.slnx                # 规范解决方案（不含 Python Server）
├── MashiruDaily.sln                 # 遗留冗余副本，勿依赖、勿维护
├── Directory.Packages.props         # 中央包版本管理
│
├── MashiruDaily.Core/               # 纯 .NET 共享领域层，无 Avalonia 依赖
│   ├── Models/                      # TodoItem、RemoteServerSettings
│   ├── Abstracts/                   # ITodoService、IRemoteSyncService 等
│   ├── Services/                    # TodoService、RemoteSyncService、Webhook 签名等
│   ├── ViewModels/                  # TodoPageViewModel、TalkViewModel 等
│   └── Logging/                     # NLog 程序化配置
│
├── MashiruDaily/                    # Avalonia 共享 UI 项目
│   ├── Views/                       # 主窗口、Todo 页、设置页、Talk 页
│   ├── ViewModels/                  # MainViewModel 等 UI 专用 VM
│   ├── Controls/                    # 底部导航、同步状态条
│   ├── Assets/                      # 图标、中文字体
│   └── App.axaml.cs                 # DI 装配入口
│
├── MashiruDaily.Desktop/            # Windows 桌面入口
├── MashiruDaily.Tui/                # Terminal.Gui 终端入口
├── MashiruDaily.Android/            # Android 入口（实验性）
├── MashiruDaily.Browser/            # Browser 入口（实验性）
├── MashiruDaily.iOS/                # iOS 入口（实验性）
├── MashiruDaily.Tests/              # .NET xUnit 测试
│
├── MashiruDaily.Server/             # Python FastAPI 后端（独立项目）
│   ├── app/                         # FastAPI 入口与数据读写
│   ├── hermes_plugin/mashiru_daily/ # Hermes 插件：工具 + 4 个 skill
│   ├── tests/                       # pytest 离线契约测试
│   ├── setup_server.py              # 初始化 .venv / 数据目录 / meta
│   ├── register_hermes_plugin.py    # 注册 Hermes 插件
│   ├── configure_webhook.py         # 配置 Hermes Webhook
│   ├── configure_cron.py            # 配置每日 Hermes 任务
│   ├── install_autostart.py         # 配置开机自启
│   ├── bootstrap.py                 # 一键装配
│   └── uninstall.py                 # 卸载部署足迹
│
└── docs/                            # 设计与通信协议文档
```

> 权威开发约束请阅读仓库根目录 `AGENTS.md`，以及各子项目内的 `AGENTS.md`。

---

## 架构与数据流

### 核心链路

```text
MashiruDaily 客户端（Desktop / TUI）
   │
   │  GET  /api/todo/meta         拉取时先比较 updated_at
   │  GET  /api/todo              服务器数据比本地新时整表覆盖
   │  GET  /api/messages          获取 Hermes Agent 消息
   │  POST /api/update            批量推送本地 Todo 变更（事件）
   ▼
MashiruDaily.Server（FastAPI :8123）
   │
   │  直接读写 todo.json / todo-meta.json / messages-to-user.json
   ▼
Hermes Agent（Webhook 网关 :8644 + cron）
   │
   │  客户端推送成功后触发 Webhook
   │  每日 cron 生成/调整学习计划
   ▼
写回 todo.json / messages-to-user.json
```

### 同步策略

1. **拉取**：客户端启动或手动同步时先 `GET /api/todo/meta`。
   - 本地 `LastSyncedAt` 为空或服务器 `updated_at` 严格更新 → 跳过推送，`GET /api/todo` 整表覆盖。
2. **推送**：本地有未同步变更时，按事件批量 `POST /api/update`（每批 ≤ 15 条）。
   - 请求体顶层携带 UTC+8 的 `updated_at`。
   - 成功后客户端推进本地 `LastSyncedAt`，避免把自己的推送误判为需要拉取。
3. **Agent 反应**：推送成功后客户端把快照写入后台 Channel，由单一 Worker POST 到 `HermesBaseUrl/webhooks/{WebhookRouteName}`，再轮询 `/api/messages` 获取 Agent 消息。

### 防回环关键纪律

- 拉取覆盖时使用 `_suppressChanged = true`，不触发本地 `Changed`。
- `TodoService.MarkSyncedAsync` 不触发 `Changed`。
- 事件入队/分发都必须持有同步 `_gate`。

---

## 快速开始

### 环境要求

- .NET SDK 10（`net10.0`）
- Python 3.10+（服务端）
- 可选：Hermes Agent 环境（用于完整每日规划功能）

### 1. 启动服务端

最简单的本地运行：

```powershell
cd MashiruDaily.Server
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
python -m app.main
```

默认监听 `0.0.0.0:8123`。

如需一键完成 Hermes 插件注册、Webhook、cron、开机自启：

```powershell
python bootstrap.py --secret <你的Webhook密钥>
```

> 详细运维手册见 `MashiruDaily.Server/README.md`。

### 2. 运行桌面端

```powershell
dotnet run --project MashiruDaily.Desktop
```

发布 Windows x64 自包含包：

```powershell
dotnet publish MashiruDaily.Desktop/MashiruDaily.Desktop.csproj `
  -c Release -r win-x64 --self-contained true `
  -o artifacts/desktop-win-x64
```

### 3. 运行 TUI

```bash
dotnet run --project MashiruDaily.Tui
```

操作：

- `↑` / `↓`：选择 Todo
- `Space`：切换完成状态
- `Tab` / `→`：在列表、删除按钮、页面之间移动焦点
- `D` / `Delete`：删除当前 Todo
- `Esc`：退出并冲刷数据

发布 linux-arm64 自包含单文件：

```bash
dotnet publish MashiruDaily.Tui/MashiruDaily.Tui.csproj \
  -c Release -r linux-arm64 --self-contained true \
  -p:PublishSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true \
  -o artifacts/tui-linux-arm64
```

---

## 客户端设置

客户端同步设置保存在：

- Windows：`%APPDATA%\MashiruDaily\settings.json`
- 其他平台：`.NET ApplicationData` 对应目录下的 `MashiruDaily\settings.json`

常用字段：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `ServerBaseUrl` | 空 | 拉取与推送统一走该地址，例如 `http://192.168.1.10:8123` |
| `HermesBaseUrl` | `http://localhost:8644` | Hermes Webhook 网关地址；设置页连接测试也用它 |
| `WebhookRouteName` | `todo-sync` | 触发 Hermes Agent 反应的 Webhook 路由名 |
| `WebhookSecret` | 空 | HMAC 签名密钥 |
| `SyncEnabled` | `false` | 是否开启远程同步 |
| `MaxRetryAttempts` | `3` | 推送最大重试次数 |
| `TimeoutSeconds` | `10` | HTTP 超时 |
| `LastSyncedAt` | 空 | 上次成功同步的服务端 `updated_at` |

> ⚠️ `ServerBaseUrl` 默认是空，开启同步后必须显式填写 FastAPI 地址（`:8123`），
> 代码里没有“默认等于 HermesBaseUrl”的回退逻辑。

---

## 服务端 API

默认监听 `0.0.0.0:8123`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/todo/meta` | 返回 `date / updated_at / count` |
| GET | `/api/todo` | 返回蛇形命名 Todo 数组 |
| GET | `/api/messages` | 返回 Agent 消息 `{ exist, text, time }` |
| POST | `/api/update` | 接收客户端批量事件推送，直接改写 `todo.json` |

另有 Hermes Webhook 网关默认在 `:8644`，路由名通常为 `todo-sync`。

---

## 数据文件

### 服务端

默认数据目录 `$HOME/.mashiru-daily/`，可用 `MASHIRU_DATA_DIR` 覆盖：

```text
$HOME/.mashiru-daily/
├── todos/
│   ├── todo.json            # 服务端唯一权威 Todo 数据（snake_case）
│   ├── todo-meta.json       # 同步元数据
│   └── backups/             # todo_save 覆盖前备份
└── messages-to-user.json    # Agent 给用户的消息
```

### 客户端

本地数据保存在应用数据目录：

```text
MashiruDaily/
├── todos.json               # 本地 Todo 数据（PascalCase）
├── settings.json            # 同步设置
└── logs/                    # NLog 文件日志
```

> ⚠️ 网络传输和服务端使用 snake_case（`is_completed` / `created_at`），
> 客户端本地持久化使用 PascalCase（`Id` / `Title`）。
> `HasSynced` 是客户端本地字段，任何事件都不得传输到服务端。

---

## 测试

### .NET

```powershell
dotnet test MashiruDaily.Tests
```

测试完全离线，远程同步测试使用 `FakeHttpMessageHandler`，不会发出真实网络请求。

### Python 服务端

```powershell
pytest MashiruDaily.Server/tests -v
```

pytest 套件完全离线，使用 in-process `TestClient` 与 monkeypatch。

---

## 打包与发布

当前 Release 主要包含三个 zip：

| 包 | 目标 | 内容 |
|---|---|---|
| `MashiruDaily.Desktop-win-x64-<版本>.zip` | Windows x64 | 桌面端自包含发布目录 |
| `MashiruDaily.Tui-linux-arm64-<版本>.zip` | linux-arm64 | TUI 自包含单文件 |
| `MashiruDaily.Server-<版本>.zip` | 任意 Python 主机 | 服务端源码包 |

桌面端打包示例：

```powershell
dotnet publish MashiruDaily.Desktop/MashiruDaily.Desktop.csproj `
  -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=false `
  -o artifacts/release/desktop
```

TUI 打包示例：

```bash
dotnet publish MashiruDaily.Tui/MashiruDaily.Tui.csproj \
  -c Release -r linux-arm64 --self-contained true \
  -p:PublishSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true \
  -o artifacts/release/tui
```

服务端源码包建议剔除 `.venv`、`__pycache__`、`.pytest_cache`、日志与本地数据后再压缩。

---

## 开发说明

- **规范解决方案**：使用 `MashiruDaily.slnx`；不要维护根目录遗留的 `.sln`。
- **提交信息**：遵循 Conventional Commits，`type: 中文描述`，例如 `feat: 新增 TodoRepoService`。
- **改同步代码前**：先读根目录 `AGENTS.md`、`MashiruDaily.Core/AGENTS.md` 与 `docs/api&webhooks/通信协议.md`。
- **服务端改动前**：阅读 `MashiruDaily.Server/AGENTS.md`。
- **TUI 改动前**：阅读 `MashiruDaily.Tui/AGENTS.md`，Terminal.Gui v2 与 v1 差异很大。
- **代码风格**：
  - 字段前加 `_`；
  - 注释与日志使用中文；
  - 每个类的声明顺序：字段 → 属性 → 事件 → 构造器 → 方法，声明之间空行分隔。
- **无 CI**：仓库当前没有 GitHub Actions / Makefile，测试与构建均在本机执行。

---

## 常见问题

### 构建报 MSB3027/MSB3026 文件被锁

通常是上一次运行的客户端/服务端进程还在占用文件：

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'MashiruDaily' } | Stop-Process -Force
```

### Avalonia 出现 “Avalonia Accelerate Community requires telemetry...”

这是 Avalonia 构建期遥测提示，属于良性提示；如不希望写入遥测日志，可设置：

```powershell
$env:AVALONIA_TELEMETRY_OPTOUT='1'
```

### 同步一直是 Error

优先检查：

1. `SyncEnabled` 是否为 `true`；
2. `ServerBaseUrl` 是否显式填写了 `http://<主机>:8123`；
3. 服务端是否真的监听在 `8123`；
4. 客户端能否访问服务端的 `8123` 与 Hermes 网关的 `8644`。

### 多端同时改数据为什么不会丢？

服务端以 `todo.json` 为唯一权威数据，客户端用 `updated_at` 决定“拉取覆盖”还是“推送合并”；
推送成功后立即推进本地 `LastSyncedAt`，避免自己的写入被误判为远端新数据。

---

## License / 说明

具体授权信息请以仓库 LICENSE 或作者声明为准。

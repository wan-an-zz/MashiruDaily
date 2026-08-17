# AGENTS.md

Avalonia 12.1 cross-platform app (net10.0) using SukiUI theming, MVVM + DI, NLog, plus a Linux/terminal TUI built on Terminal.Gui v2 and a Python FastAPI pull server. Solution: `MashiruDaily.slnx`（不含 Python 服务端与临时探针工程）。另有遗留的经典格式 `MashiruDaily.sln`（同 8 项目、同样被 git 跟踪）— 冗余副本，勿依赖、勿维护。Branch convention: feature branches pushed to origin（分支名中英混杂，如 `feature/服务端`、`feature/拉取流和Webhooks`、`feature/HermesWebhook`；当前在 `feature/服务端`；`master`/`develop` 本机与远端都有）。

## 项目概要
这是一个面向初、高中学生的、由Hermes Agent驱动的Todo List项目。.NET项目为客户端的Todo List项目，Python项目为依赖于Hermes Agent的用户自部署后端项目。该项目中，后端的Hermes Agent扮演**规划者**的角色，每天定时为用户制定当日的学习计划（Todo），客户端会主动拉取Todo并呈现给用户。当客户端的Todo出现增加、删除、修改等操作时，会通过Hermes Webhooks反映给Hermes Agent，让其在后端做出相应的决策。客户端的数据源来自后端，客户端的改动会同步至后端。(Hermes Docs: https://hermes-agent.nousresearch.com/docs)

## Git 提交规范

提交信息遵循[约定式提交规范](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>: <描述>
```

- `<type>` 使用英文标准类型：`feat`（新功能）、`fix`（修复）、`refactor`（重构）、`docs`（文档）、`test`（测试）、`chore`（杂务/构建/配置）、`perf`（性能）、`build`（构建）、`ci`（CI）、`style`（格式）、`revert`（回滚）。
- `<描述>` 使用中文，简洁说明本次改动；`type:` 后必须有一个空格。
- 示例：`feat: 新增 JsonTodoRepository，JSON 持久化到 ApplicationData`、`fix: 落盘改为值快照并支持关闭时冲刷`。

## 项目地图（重要 — 多项目边界）

共享领域代码在 **`MashiruDaily.Core`**（纯 .NET 类库，**无 Avalonia 依赖**，但引 CommunityToolkit.Mvvm），各 UI 项目都引用它：

- `MashiruDaily.Core/` — 后端 + 日志 + 视图模型（命名空间仍是 `MashiruDaily.*`）：`Models/TodoItem`+`HermesSettings`、`Abstracts/ITodoService`+`ITodoRepository`+`IHermesSettingsRepository`+`IHermesSyncService`、`Services/TodoService`+`JsonTodoRepository`+`JsonHermesSettingsRepository`+`HermesSyncService`+`HermesWebhookSigner`、`Converters/LocalDateTimeJsonConverter`、`Logging/LoggingConfigurator`、`ViewModels/ViewModelBase`+`ViewModels/Todo/*`。**先读 `MashiruDaily.Core/AGENTS.md`**，里面是领域层与同步子系统的权威规范。
- `MashiruDaily/`（Avalonia 共享项目）— 引用 Core；保留 UI 专属：`Models/NavigationItem`、`Abstracts/INavigationItem`、`ViewModels/MainViewModel`+`SettingsPageViewModel`、`Views/`（含 `Todo/TodoPageView`、`SettingsPageView`）、`Controls/`（`BottomNavigationBar*`、`SyncStatusBar`）、`Assets/`、`App.axaml*`。桌面/Android/Browser/iOS 都引用它。
- `MashiruDaily.Tui/`（Terminal.Gui v2 控制台，Linux 可运行）— 引用 **Core**（不是 `MashiruDaily`，避免拖入 Avalonia）。`Program.cs`（DI + 生命周期）+ `Views/MainWindow`、`TodoColumnView`、`TodoRowView`。**先读 `MashiruDaily.Tui/AGENTS.md`**，里面是 Terminal.Gui v2 权威规范。
- `MashiruDaily.Tests/`（xUnit）— 引用 Core 与 MashiruDaily。
- `MashiruDaily.Server/` — Python 后端（FastAPI），**不是 .NET 项目、不在 slnx 里**，两职责：① 拉取服务器（只读 GET，默认监听 `0.0.0.0:8123`：`/health`、`/api/todo/meta`、`/api/todo`），数据源 `data/todo.json`；② Hermes 装配工具集（`bootstrap.py` 一键串联 setup_server → register_skills → configure_webhook → configure_cron → install_autostart）。**TDD**：先写契约测试（RED）再实现 `app/main.py` 转绿。运维手册就是它自己的 `README.md`，动手前先读；**代理规范见 `MashiruDaily.Server/AGENTS.md`**。关键纪律：`todo-meta.json` 的 `createdAt` **只在 Hermes 插件工具 `todo_meta_stamp` 运行时改变**（运行时机仅两处：`setup_server.py` 首次引导与每日 cron agent 结束，见其 `README.md` §6） —— webhook 驱动的 `todo.json` 修改绝不能碰侧车，否则客户端每次同步后都会因时间戳更新而误判「需要拉取」，造成无谓的全量拉取。
- `HeadlessProbe/` — TUI 无头调试的临时探针工程，仓库里只剩 bin/obj 构建产物、已被 .gitignore 忽略、不在解决方案里；看到可忽略，别加进 slnx。
- 三端共享同一后端与数据：都是 `TodoService` + `JsonTodoRepository`，落到 `%APPDATA%\MashiruDaily\todos.json`；同步设置经 `JsonHermesSettingsRepository` 落到同目录 `settings.json`。
- **改同步相关代码前先读 `docs/design/通信协议.md`** — 与 Hermes 同步的权威契约（`docs/design/*` 被 .gitignore 忽略，仅放行 `通信协议.md` 与 `通信协议示例.json` 两个文件提交），端点/字段/默认值/语义以它为准，客户端实现不得偏离。

## Build / run

- 共享/后端：`dotnet build MashiruDaily` 或 `dotnet build MashiruDaily.Core`
- 桌面：`dotnet build MashiruDaily.Desktop` / `dotnet run --project MashiruDaily.Desktop`
- TUI：`dotnet build MashiruDaily.Tui` / `dotnet run --project MashiruDaily.Tui`（Esc 退出并冲刷）
- Android：`dotnet build MashiruDaily.Android` (needs Android workload + SDK; runs on device/emulator via IDE)
- 测试：`dotnet test MashiruDaily.Tests` — 完全离线（Hermes 同步测试用 FakeHttpMessageHandler 桩 HTTP，不会真发网络请求）
- 服务端契约测试：`pytest MashiruDaily.Server/tests -v`（完全离线，52 个用例）；手动启动：`.venv\Scripts\python.exe -m app.main`（详见 `MashiruDaily.Server/README.md`）
- 一个良性的 `Avalonia Accelerate Community requires telemetry...` 提示每次构建都出现 — 忽略它。
- 若构建报 MSB3027/MSB3026（文件被 `.NET Host` 锁住），说明上个应用实例还在跑 — 杀掉重编：`Get-Process | ? ProcessName -match MashiruDaily | Stop-Process -Force`。

## Architecture (key files)

- `MashiruDaily.Core/Abstracts/` — 接口；`Services/TodoService`（单一数据源，变更时抛 `Changed`，单飞冲刷循环落盘值快照）+ `JsonTodoRepository`（原子写：tmp 文件 + move）。
- `MashiruDaily.Core/ViewModels/Todo/` — `TodoPageViewModel`（拆待完成/已完成集合）、`TodoItemViewModel`（编辑态）。TUI 直接消费这些 VM。
- **Hermes 同步子系统（全在 Core，三端共用）**：
  - `HermesSyncService`（`partial : ObservableObject` + `[ObservableProperty]`，非 Avalonia）— 启动先拉 meta（`GET {ServerBaseUrl}/api/todo/meta`）比对 `createdAt`：`LastSyncedAt` 为空或服务器 `createdAt` 严格更晚 → 跳过推送、`GET {ServerBaseUrl}/api/todo` 整表覆盖（`ReplaceAllAsync` + `_suppressChanged=true`）并持久化 `LastSyncedAt`；否则推送 `HasSynced=false` 条目（统一 `todo_updated` upsert）事件**串行** POST（限流安全），429 退避 2s，`MaxRetryAttempts+1` 次后置 `Error`。事件类型 5 种：`todo_added`/`todo_updated`/`todo_completed`/`todo_reopened`/`todo_deleted`，payload 一律为完整条目快照。
  - `HermesWebhookSigner` — HMAC-SHA256 小写 hex，对 `"{timestamp}.{rawBody}"` 原始字节计算；请求头 `X-Webhook-Timestamp`/`X-Webhook-Signature-V2`/`X-Request-ID`。
  - `JsonHermesSettingsRepository` — `settings.json` 原子写；缺省按 `HermesSettings.CreateDefault()`（`SyncEnabled=false`，不联网）。
  - **防回环（改同步代码必知）**：拉取覆盖时 `_suppressChanged=true`；`TodoService.MarkSyncedAsync` 不触发 `Changed`。破坏任一条 → webhook 回声/死循环。
  - **`ServerBaseUrl` 陷阱**：拉取服务器（8123，FastAPI）与 Hermes webhook 网关（8644）是两个独立地址。代码里 `ServerBaseUrl` 默认是空串，**没有**协议附录里「默认同 `HermesBaseUrl`」的回退逻辑，且 `Validate()` 在 `SyncEnabled` 时强制必填 —— 必须显式填 `http://<主机>:8123`，否则拉取请求打到空地址、同步恒为 `Error`。改拉取逻辑时以代码为准，别照抄协议附录的默认值。
- `MashiruDaily/App.axaml.cs` `ConfigureServices()` — DI 装配（Todo 两件套 + Hermes 三件套 + `HttpClient` 单例 + 三个页面 VM）；根容器暴露为 `App.Services`。Tui 的 `Program.cs` 用同样的注册。
- `Views/` 用 `ViewLocator`（反射：`ViewModel`→`View`）；保持 `XxxViewModel`/`XxxView` 成对且在平行命名空间，否则页面解析不到。
- `Controls/BottomNavigationBar/` — 自定义控件，自带主题 `.axaml` 并入 `App.axaml` `Application.Resources`。
- 设置页 `SettingsPageViewModel`：连接测试打 `GET {HermesBaseUrl}/health`；「立即同步」走 `IHermesSyncService.SyncNowAsync()`。

## Gotchas

- **CJK text on Android renders as empty boxes (tofu)** unless the bundled font fallback is wired up: `Assets/Fonts/NotoSansSC-Regular.ttf` (GB2312 subset) + `NotoSansSCFontCollection` + `AppFonts.CreateFontManagerOptions()`. Order matters in the platform builders (both `MashiruDaily.Desktop/Program.cs` and `MashiruDaily.Android/Application.cs`): `.With(FontManagerOptions)` MUST come before `.ConfigureFonts(...)`/`.WithInterFont()`, otherwise fallback never applies.
- SukiUI is desktop-only. Android must NOT use SukiWindow/SukiSideMenu; shared styling must use SukiUI DynamicResources (`SukiPrimaryColor*`, `SukiCardBackground`, etc.), which work on both.
- NLog is configured programmatically in `MashiruDaily.Core/Logging/LoggingConfigurator.cs` (no nlog.config); file logs land in `%APPDATA%\MashiruDaily\logs\`.
- `AvaloniaUseCompiledBindingsByDefault=true` — always set `x:DataType`; compiled bindings fail the build on type errors (good) and `{x:Static}` icon refs resolve against `Assets/AppIcons.cs`.
- Central package versions: edit `Directory.Packages.props` (not csproj) to bump versions; keep the Avalonia 12.1.x `PackageVersion` entries in sync (`Terminal.Gui`/`DiagnosticsSupport` have their own versions).
- `MashiruDaily.csproj` has `<AvaloniaResource Include="Assets\**"/>` so any new `.axaml`/font under `Assets/` is embedded automatically.
- `docs/superpowers/` 被 .gitignore 忽略 — 设计/计划文档不提交（若要保留只能留在工作区）。
- **字段命名大小写陷阱**：webhook 请求体 payload 是 camelCase（`isCompleted`/`createdAt`/`completedAt`）；本地 `todos.json` 与 `GET /api/todo` 是 PascalCase（`Id`/`Title`）；`HasSynced` 是客户端本地字段，**任何事件都不得传输**。
- **`通信协议.md` 的状态标注已过时**：第 5 章与文档开头的「GET 端点为服务端契约、服务端尚未实现」已不成立 —— `MashiruDaily.Server` 已按该契约实现 `/api/todo/meta` 与 `/api/todo`（`tests/test_api.py` 9 个契约测试通过）。契约本身（端点/字段/默认值/语义）仍是权威，改同步代码仍以它为准，但别再把服务端当「未实现」处理。
- **Hermes 测试模式**：`HermesSyncServiceTests` 用 `FakeHttpMessageHandler`/`ThrowingHttpMessageHandler` 注入 `HttpClient` + `CreateHarnessAsync`（临时目录 + 真实 repo/service）+ `WaitUntilAsync` 轮询断言 —— 不 mock `TodoService`，新同步测试沿用该模式。
- Android 已放行明文 HTTP（`AndroidManifest.xml`，commit 6fca148）以支持局域网 webhook；桌面/TUI 无此限制。
- **TUI 键盘路由（Terminal.Gui v2 核心坑，改过 3 次才修对）**：
  - 按键经 `KeyDown` 事件沿焦点链冒泡到列处理，**不要用 `KeyBindings`**（它只在视图自身有焦点时生效；真实初始焦点常落在子控件上）。
  - 焦点链要求**每个祖先 `CanFocus=true`** 才能聚焦其子视图；容器 `CanFocus=false` 会切断链，导致除 Esc（应用级 Quit）外所有键失效。TUI 的 `content`、`TodoColumnView._listArea`、`TodoRowView` 都必须 `CanFocus=true`，删除按钮才能被 `SetFocus()`。
  - `Command.Delete` 在 v2 中**不存在**（只有文本编辑类 Delete 命令）；D/Delete 用 `KeyDown` 里比较 `Key.D`/`Key.Delete`。
  - Space 已由框架绑定到 `Command.Toggle`，再显式绑定会抛重复绑定异常。
  - `Application.Run(IRunnable)` **不会**自动初始化，必须先 `app.Init()`（泛型 `Run<T>()` 才会自动初始化）。

## Anti-Patterns（代码注释里钉死的禁区，改代码前必读）

- **同步事件循环（防回环）**：`_suppressChanged` 只在拉取覆盖时置位；`MarkSyncedAsync` 永不触发 `Changed`；`HermesSyncService` 的事件入队/分发全部要求**调用方持有 `_gate`**（`InitializeAsync`/`SyncNowAsync`/`FlushAsync`/`DispatchPendingAsync` 都 `WaitAsync` 包住，破坏任一 → 竞态/死循环）。
- **Webhook 密钥**：来自 `--secret` 或环境变量 `MASHIRU_WEBHOOK_SECRET`，**禁止硬编码、禁止交互输入、禁止进命令行、禁止打印**（打印前深拷贝 + 掩码 `***`）。`bootstrap.py` 经环境变量注入子进程。
- **服务端 stdout/stderr 合并匹配**：`configure_webhook.py` 判 Hermes 网关降级信号（root 拒绝 / "User systemd not reachable"）时，两个信号可能落在不同输出流，必须 `stderr + stdout` 合并后再匹配。
- **crontab 禁用标记是启用标记的子串**：`install_autostart.py` 匹配时必须先匹配更长的禁用标记，否则禁用行被误判为启用。
- **subprocess 解码**：`_config.py` 跑子进程一律 `errors="replace"` 容错，避免中文输出炸崩溃。
- **启动/关闭不得阻塞 UI 于网络**：`App.axaml.cs` 启动同步是即发即忘，关闭冲刷尽力而为（`IHermesSyncService.FlushAsync` 契约「绝不抛异常」）。
- **Desktop 入口**：`Program.cs` 在 `AppMain` 前**不得使用任何 Avalonia/第三方 API 或依赖 SynchronizationContext 的代码**。
- **服务端数据形状**：`todo.json` 顶层必须是 JSON 数组、`todo-meta.json` 键完整，否则统一抛 `ValueError` → 500 JSON `detail`（不许 KeyError 裸崩）。
- **幂等脚本**：所有 `MashiruDaily.Server` 装配脚本幂等可重跑；改 `config.yaml` 前必须备份 `config.yaml.bak-<时间戳>`；`register_skills.py` 遇已存在插件目录**绝不覆盖**；cron 任务名判断要求词边界（防 `mashiru-daily-backup` 误判）。

## Style

> 本部分内容为代码风格的规范，你必须遵顼这个风格规范编写代码。

- 每个类的内部应按照如下顺序进行声明：1.字段声明；2.属性声明；3.事件声明；4.构造器声明；5.方法声明。
- 在每个声明之间必须有空行作为分隔，如字段与字段之间、字段与属性之间、属性与方法之间都需要有空行分隔。
- 字段前必须要有`_`作为标识，如：`_list`、`_service`，包括被特性标记的字段也必须要有`_`作为标识。除非是public static readonly 字段或public const string 常量。
- 注释必须使用中文，日志必须使用中文。

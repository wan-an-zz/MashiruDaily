# AGENTS.md

Avalonia 12.1 cross-platform app (net10.0) using SukiUI theming, MVVM + DI, NLog, plus a Linux/terminal TUI built on Terminal.Gui v2. Solution: `MashiruDaily.slnx`. Branch convention: feature branches pushed to origin (currently `feature/HermesWebhook`; `master`/`develop` exist as remotes).

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

- `MashiruDaily.Core/` — 后端 + 日志 + 视图模型（命名空间仍是 `MashiruDaily.*`）：`Models/TodoItem`+`HermesSettings`、`Abstracts/ITodoService`+`ITodoRepository`+`IHermesSettingsRepository`+`IHermesSyncService`、`Services/TodoService`+`JsonTodoRepository`+`JsonHermesSettingsRepository`+`HermesSyncService`+`HermesWebhookSigner`、`Logging/LoggingConfigurator`、`ViewModels/ViewModelBase`+`ViewModels/Todo/*`。
- `MashiruDaily/`（Avalonia 共享项目）— 引用 Core；保留 UI 专属：`Models/NavigationItem`、`Abstracts/INavigationItem`、`ViewModels/MainViewModel`+`SettingsPageViewModel`、`Views/`（含 `Todo/TodoPageView`、`SettingsPageView`）、`Controls/`（`BottomNavigationBar*`、`SyncStatusBar`）、`Assets/`、`App.axaml*`。桌面/Android/Browser/iOS 都引用它。
- `MashiruDaily.Tui/`（Terminal.Gui v2 控制台，Linux 可运行）— 引用 **Core**（不是 `MashiruDaily`，避免拖入 Avalonia）。`Program.cs`（DI + 生命周期）+ `Views/MainWindow`、`TodoColumnView`、`TodoRowView`。**先读 `MashiruDaily.Tui/AGENTS.md`**，里面是 Terminal.Gui v2 权威规范。
- `MashiruDaily.Tests/`（xUnit）— 引用 Core 与 MashiruDaily。
- 三端共享同一后端与数据：都是 `TodoService` + `JsonTodoRepository`，落到 `%APPDATA%\MashiruDaily\todos.json`；同步设置经 `JsonHermesSettingsRepository` 落到同目录 `settings.json`。
- **改同步相关代码前先读 `docs/design/通信协议.md`** — 与 Hermes 同步的权威契约（`docs/design/*` 仅这一个文件被 .gitignore 放行提交），端点/字段/默认值/语义以它为准，客户端实现不得偏离。

## Build / run

- 共享/后端：`dotnet build MashiruDaily` 或 `dotnet build MashiruDaily.Core`
- 桌面：`dotnet build MashiruDaily.Desktop` / `dotnet run --project MashiruDaily.Desktop`
- TUI：`dotnet build MashiruDaily.Tui` / `dotnet run --project MashiruDaily.Tui`（Esc 退出并冲刷）
- Android：`dotnet build MashiruDaily.Android` (needs Android workload + SDK; runs on device/emulator via IDE)
- 测试：`dotnet test MashiruDaily.Tests` — 完全离线（Hermes 同步测试用 FakeHttpMessageHandler 桩 HTTP，不会真发网络请求）
- 一个良性的 `Avalonia Accelerate Community requires telemetry...` 提示每次构建都出现 — 忽略它。
- 若构建报 MSB3027/MSB3026（文件被 `.NET Host` 锁住），说明上个应用实例还在跑 — 杀掉重编：`Get-Process | ? ProcessName -match MashiruDaily | Stop-Process -Force`。

## Architecture (key files)

- `MashiruDaily.Core/Abstracts/` — 接口；`Services/TodoService`（单一数据源，变更时抛 `Changed`，单飞冲刷循环落盘值快照）+ `JsonTodoRepository`（原子写：tmp 文件 + move）。
- `MashiruDaily.Core/ViewModels/Todo/` — `TodoPageViewModel`（拆待完成/已完成集合）、`TodoItemViewModel`（编辑态）。TUI 直接消费这些 VM。
- **Hermes 同步子系统（全在 Core，三端共用）**：
  - `HermesSyncService`（`partial : ObservableObject` + `[ObservableProperty]`，非 Avalonia）— 启动先拉 meta 比对 `createdAt`：`LastSyncedAt` 为空或服务器 `createdAt` 严格更晚 → 跳过推送、`GET /api/todo` 整表覆盖并持久化 `LastSyncedAt`；否则推送 `HasSynced=false` 条目（统一 `todo_updated` upsert）事件**串行** POST（限流安全），429 退避 2s，`MaxRetryAttempts+1` 次后置 `Error`。
  - `HermesWebhookSigner` — HMAC-SHA256 小写 hex，对 `"{timestamp}.{rawBody}"` 原始字节计算；请求头 `X-Webhook-Timestamp`/`X-Webhook-Signature-V2`/`X-Request-ID`。
  - `JsonHermesSettingsRepository` — `settings.json` 原子写；缺省按 `HermesSettings.CreateDefault()`（`SyncEnabled=false`，不联网）。
  - **防回环（改同步代码必知）**：拉取覆盖时 `_suppressChanged=true`；`TodoService.MarkSyncedAsync` 不触发 `Changed`。破坏任一条 → webhook 回声/死循环。
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
- **Hermes 测试模式**：`HermesSyncServiceTests` 用 `FakeHttpMessageHandler`/`ThrowingHttpMessageHandler` 注入 `HttpClient` + `CreateHarnessAsync`（临时目录 + 真实 repo/service）+ `WaitUntilAsync` 轮询断言 —— 不 mock `TodoService`，新同步测试沿用该模式。
- Android 已放行明文 HTTP（`AndroidManifest.xml`，commit 6fca148）以支持局域网 webhook；桌面/TUI 无此限制。
- **TUI 键盘路由（Terminal.Gui v2 核心坑，改过 3 次才修对）**：
  - 按键经 `KeyDown` 事件沿焦点链冒泡到列处理，**不要用 `KeyBindings`**（它只在视图自身有焦点时生效；真实初始焦点常落在子控件上）。
  - 焦点链要求**每个祖先 `CanFocus=true`** 才能聚焦其子视图；容器 `CanFocus=false` 会切断链，导致除 Esc（应用级 Quit）外所有键失效。TUI 的 `content`、`TodoColumnView._listArea`、`TodoRowView` 都必须 `CanFocus=true`，删除按钮才能被 `SetFocus()`。
  - `Command.Delete` 在 v2 中**不存在**（只有文本编辑类 Delete 命令）；D/Delete 用 `KeyDown` 里比较 `Key.D`/`Key.Delete`。
  - Space 已由框架绑定到 `Command.Toggle`，再显式绑定会抛重复绑定异常。
  - `Application.Run(IRunnable)` **不会**自动初始化，必须先 `app.Init()`（泛型 `Run<T>()` 才会自动初始化）。

## Style

> 本部分内容为代码风格的规范，你必须遵顼这个风格规范编写代码。

- 每个类的内部应按照如下顺序进行声明：1.字段声明；2.属性声明；3.事件声明；4.构造器声明；5.方法声明。
- 在每个声明之间必须有空行作为分隔，如字段与字段之间、字段与属性之间、属性与方法之间都需要有空行分隔。
- 字段前必须要有`_`作为标识，如：`_list`、`_service`，包括被特性标记的字段也必须要有`_`作为标识。除非是public static readonly 字段或public const string 常量。
- 注释必须使用中文，日志必须使用中文。

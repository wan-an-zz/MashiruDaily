# AGENTS.md

Avalonia 12.1 cross-platform app (net10.0) using SukiUI theming, MVVM + DI, NLog, plus a Linux/terminal TUI built on Terminal.Gui v2. Solution: `MashiruDaily.slnx`. Branch convention: feature branches (currently `feature/TUI`).

## Git 提交规范

提交信息遵循[约定式提交规范](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>: <描述>
```

- `<type>` 使用英文标准类型：`feat`（新功能）、`fix`（修复）、`refactor`（重构）、`docs`（文档）、`test`（测试）、`chore`（杂务/构建/配置）、`perf`（性能）、`build`（构建）、`ci`（CI）、`style`（格式）、`revert`（回滚）。
- `<描述>` 使用中文，简洁说明本次改动；`type:` 后必须有一个空格。
- 示例：`feat: 新增 JsonTodoRepository，JSON 持久化到 ApplicationData`、`fix: 落盘改为值快照并支持关闭时冲刷`。

## 项目地图（重要 — 多项目边界）

共享领域代码在 **`MashiruDaily.Core`**（纯 .NET 类库，**无 Avalonia 依赖**），各 UI 项目都引用它：

- `MashiruDaily.Core/` — 后端 + 日志 + Todo 视图模型（命名空间仍是 `MashiruDaily.*`）：`Models/TodoItem`、`Abstracts/ITodoService`+`ITodoRepository`、`Services/TodoService`+`JsonTodoRepository`、`Logging/LoggingConfigurator`、`ViewModels/ViewModelBase`+`ViewModels/Todo/*`。
- `MashiruDaily/`（Avalonia 共享项目）— 引用 Core；保留 UI 专属：`Models/NavigationItem`、`Abstracts/INavigationItem`、`ViewModels/MainViewModel`、`Views/`、`Controls/`、`Assets/`、`App.axaml*`。桌面/Android/Browser/iOS 都引用它。
- `MashiruDaily.Tui/`（Terminal.Gui v2 控制台，Linux 可运行）— 引用 **Core**（不是 `MashiruDaily`，避免拖入 Avalonia）。`Program.cs`（DI + 生命周期）+ `Views/MainWindow`、`TodoColumnView`、`TodoRowView`。**先读 `MashiruDaily.Tui/AGENTS.md`**，里面是 Terminal.Gui v2 权威规范。
- `MashiruDaily.Tests/`（xUnit）— 引用 Core 与 MashiruDaily。
- 三端共享同一后端与数据：都是 `TodoService` + `JsonTodoRepository`，落到 `%APPDATA%\MashiruDaily\todos.json`。

## Build / run

- 共享/后端：`dotnet build MashiruDaily` 或 `dotnet build MashiruDaily.Core`
- 桌面：`dotnet build MashiruDaily.Desktop` / `dotnet run --project MashiruDaily.Desktop`
- TUI：`dotnet build MashiruDaily.Tui` / `dotnet run --project MashiruDaily.Tui`（Esc 退出并冲刷）
- Android：`dotnet build MashiruDaily.Android` (needs Android workload + SDK; runs on device/emulator via IDE)
- 测试：`dotnet test MashiruDaily.Tests`
- 一个良性的 `Avalonia Accelerate Community requires telemetry...` 提示每次构建都出现 — 忽略它。
- 若构建报 MSB3027/MSB3026（文件被 `.NET Host` 锁住），说明上个应用实例还在跑 — 杀掉重编：`Get-Process | ? ProcessName -match MashiruDaily | Stop-Process -Force`。

## Architecture (key files)

- `MashiruDaily.Core/Abstracts/` — 接口；`Services/TodoService`（单一数据源，变更时抛 `Changed`）+ `JsonTodoRepository`（原子写：tmp 文件 + move）。
- `MashiruDaily.Core/ViewModels/Todo/` — `TodoPageViewModel`（拆待完成/已完成集合）、`TodoItemViewModel`（编辑态）。TUI 直接消费这些 VM。
- `MashiruDaily/App.axaml.cs` `ConfigureServices()` — DI 装配（`ITodoRepository→JsonTodoRepository`、`ITodoService→TodoService`、`TodoPageViewModel`、`MainViewModel`）；根容器暴露为 `App.Services`。Tui 的 `Program.cs` 用同样的注册。
- `Views/` 用 `ViewLocator`（反射：`ViewModel`→`View`）；保持 `XxxViewModel`/`XxxView` 成对且在平行命名空间，否则页面解析不到。
- `Controls/BottomNavigationBar/` — 自定义控件，自带主题 `.axaml` 并入 `App.axaml` `Application.Resources`。

## Gotchas

- **CJK text on Android renders as empty boxes (tofu)** unless the bundled font fallback is wired up: `Assets/Fonts/NotoSansSC-Regular.ttf` (GB2312 subset) + `NotoSansSCFontCollection` + `AppFonts.CreateFontManagerOptions()`. Order matters in the platform builders (both `MashiruDaily.Desktop/Program.cs` and `MashiruDaily.Android/Application.cs`): `.With(FontManagerOptions)` MUST come before `.ConfigureFonts(...)`/`.WithInterFont()`, otherwise fallback never applies.
- SukiUI is desktop-only. Android must NOT use SukiWindow/SukiSideMenu; shared styling must use SukiUI DynamicResources (`SukiPrimaryColor*`, `SukiCardBackground`, etc.), which work on both.
- NLog is configured programmatically in `MashiruDaily.Core/Logging/LoggingConfigurator.cs` (no nlog.config); file logs land in `%APPDATA%\MashiruDaily\logs\`.
- `AvaloniaUseCompiledBindingsByDefault=true` — always set `x:DataType`; compiled bindings fail the build on type errors (good) and `{x:Static}` icon refs resolve against `Assets/AppIcons.cs`.
- Central package versions: edit `Directory.Packages.props` (not csproj) to bump versions; keep the Avalonia 12.1.x `PackageVersion` entries in sync (`Terminal.Gui`/`DiagnosticsSupport` have their own versions).
- `MashiruDaily.csproj` has `<AvaloniaResource Include="Assets\**"/>` so any new `.axaml`/font under `Assets/` is embedded automatically.
- `docs/superpowers/` 被 .gitignore 忽略 — 设计/计划文档不提交（若要保留只能留在工作区）。
- **TUI 键盘路由（Terminal.Gui v2 核心坑，改过 3 次才修对）**：
  - 按键经 `KeyDown` 事件沿焦点链冒泡到列处理，**不要用 `KeyBindings`**（它只在视图自身有焦点时生效；真实初始焦点常落在子控件上）。
  - 焦点链要求**每个祖先 `CanFocus=true`** 才能聚焦其子视图；容器 `CanFocus=false` 会切断链，导致除 Esc（应用级 Quit）外所有键失效。TUI 的 `content`、`TodoColumnView._listArea`、`TodoRowView` 都必须 `CanFocus=true`，删除按钮才能被 `SetFocus()`。
  - `Command.Delete` 在 v2 中**不存在**（只有文本编辑类 Delete 命令）；D/Delete 用 `KeyDown` 里比较 `Key.D`/`Key.Delete`。
  - Space 已由框架绑定到 `Command.Toggle`，再显式绑定会抛重复绑定异常。
  - `Application.Run(IRunnable)` **不会**自动初始化，必须先 `app.Init()`（泛型 `Run<T>()` 才会自动初始化）。

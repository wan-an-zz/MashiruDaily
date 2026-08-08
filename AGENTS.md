# AGENTS.md

Avalonia 12.1 cross-platform app (net10.0) using SukiUI theming, MVVM + DI, NLog. Solution: `MashiruDaily.slnx`. Branch convention: feature branches (currently `feature/TODO列表`).

## Git 提交规范

提交信息遵循[约定式提交规范](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>: <描述>
```

- `<type>` 使用英文标准类型：`feat`（新功能）、`fix`（修复）、`refactor`（重构）、`docs`（文档）、`test`（测试）、`chore`（杂务/构建/配置）、`perf`（性能）、`build`（构建）、`ci`（CI）、`style`（格式）、`revert`（回滚）。
- `<描述>` 使用中文，简洁说明本次改动；`type:` 后必须有一个空格。
- 示例：`feat: 新增 JsonTodoRepository，JSON 持久化到 ApplicationData`、`fix: 落盘改为值快照并支持关闭时冲刷`。

## Build / run

- Desktop: `dotnet build MashiruDaily.Desktop` / `dotnet run --project MashiruDaily.Desktop`
- Android: `dotnet build MashiruDaily.Android` (needs Android workload + SDK; runs on device/emulator via IDE)
- A benign `Avalonia Accelerate Community requires telemetry...` notice appears on every build — ignore it.
- If a build fails with MSB3027/MSB3026 (file locked by `.NET Host`), a previous app instance is still running — kill it (`Get-Process | ? ProcessName -match MashiruDaily | Stop-Process -Force`) and rebuild.
- Shared project: `dotnet build MashiruDaily`.

## Architecture (key files)

- `Abstracts/` — the only interfaces (`ITodoService`, `ITodoRepository`, `INavigationItem`); depends on `Models/` and `ViewModels/`.
- `Services/` — concrete `TodoService` (single source of truth, raises `Changed`), `JsonTodoRepository` (JSON 持久化到 ApplicationData).
- `ViewModels/` — `MainViewModel` (navigation items list shared by desktop + Android), `Todo/TodoPageViewModel` + `TodoItemViewModel` (inline edit state).
- `Views/` — `MainWindow` (desktop: SukiWindow + SukiSideMenu), `MainView` (Android: BottomNavigationBar), shared `Todo/TodoPageView`.
- `Views/` use `ViewLocator` (reflection: `ViewModel`→`View`); keep a `XxxViewModel`/`XxxView` pair in parallel namespaces or the page won't resolve.
- `Controls/BottomNavigationBar/` — custom controls with their own theme `.axaml` merged into `App.axaml` `Application.Resources`.
- DI lives in `App.axaml.cs` `ConfigureServices()`; root container exposed as `App.Services`.

## Gotchas

- **CJK text on Android renders as empty boxes (tofu)** unless the bundled font fallback is wired up: `Assets/Fonts/NotoSansSC-Regular.ttf` (GB2312 subset) + `NotoSansSCFontCollection` + `AppFonts.CreateFontManagerOptions()`. Order matters in the platform builders (both `MashiruDaily.Desktop/Program.cs` and `MashiruDaily.Android/Application.cs`): `.With(FontManagerOptions)` MUST come before `.ConfigureFonts(...)`/`.WithInterFont()`, otherwise fallback never applies.
- SukiUI is desktop-only. Android must NOT use SukiWindow/SukiSideMenu; shared styling must use SukiUI DynamicResources (`SukiPrimaryColor*`, `SukiCardBackground`, etc.), which work on both.
- NLog is configured programmatically in `Logging/LoggingConfigurator.cs` (no nlog.config); file logs land in `%APPDATA%\MashiruDaily\logs\`.
- `AvaloniaUseCompiledBindingsByDefault=true` — always set `x:DataType`; compiled bindings fail the build on type errors (good) and `{x:Static}` icon refs resolve against `Assets/AppIcons.cs`.
- Central package versions: edit `Directory.Packages.props` (not csproj) to bump Avalonia/SukiUI/NLog/DI; keep the 4 Avalonia `PackageVersion` entries in sync.
- `MashiruDaily.csproj` has `<AvaloniaResource Include="Assets\**"/>` so any new `.axaml`/font under `Assets/` is embedded automatically.

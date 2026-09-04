# AGENTS.md — MashiruDaily（Avalonia 共享 UI 项目）

> 本目录是 Avalonia 共享项目（net10.0），桌面 / Android / Browser / iOS 四个平台头都引用它。业务逻辑在 `MashiruDaily.Core`（不引 Avalonia），**本目录只放 UI 专属代码**：页面、自定义控件、导航模型、DI 装配。

## 概览

以 `MashiruDaily.Core.ViewModels` 为数据源，用 `ViewLocator` 反射把 VM 映射到本目录的 View；DI 在 `App.axaml.cs` 的 `ConfigureServices()` 装配（根容器暴露为 `App.Services`），TUI 的 `Program.cs` 用同样的 Core 注册（只是少了本目录的两个 VM）。

## 目录

| 目录 | 内容 | 备注 |
|---|---|---|
| `Views/` | `MainWindow.axaml*`（桌面 SukiWindow）、`MainView.axaml*`（单视图/移动）、`SettingsPageView.axaml*`、`Todo/TodoPageView.axaml*`、`TalkView.axaml*` | 全部 `UserControl`（除 MainWindow）；`ViewLocator` 按命名空间映射 |
| `Controls/` | 平铺三件套：`BottomNavigationBar.axaml*`、`BottomNavigationItem.axaml*`、`SyncStatusBar.axaml*` | 自定义控件自带主题 `.axaml`，并入 `App.axaml` `Application.Resources` |
| `ViewModels/` | `MainViewModel`、`SettingsPageViewModel` | Avalonia 侧 VM（Core 的 `TodoPageViewModel` 在 Core 里） |
| `Models/`+`Abstracts/` | `NavigationItem` + `INavigationItem` | 底部导航数据模型 |
| `Assets/` | `AppIcons.cs`（`{x:Static}` 图标源）、`AppFonts.cs`/`NotoSansSCFontCollection.cs`、`Fonts/NotoSansSC-Regular.ttf` | 中文字体回退（Android tofu 修复） |

## ViewLocator 反射约定（新增页面必读）

`ViewLocator.cs`：把 `XxxViewModel` 的 `FullName` 做两次字符串替换得到 View 类型：
`MashiruDaily.Core.ViewModels` → `MashiruDaily.Views`，`ViewModel` → `View`。

- **命名空间必须平行**：`MashiruDaily.Core.ViewModels.Todo.TodoPageViewModel` → `MashiruDaily.Views.Todo.TodoPageView`。
- 找不到类型时返回「未找到视图：{name}」TextBlock（静默失败，不抛错）—— 新增页面若解析不到，先查命名空间/命名是否成对。
- `Match()` 只认 `ViewModelBase` 子类；UI 侧 VM（如 `MainViewModel`）必须继承 `ViewModelBase`（在 Core）。

## 绑定与样式

- **`AvaloniaUseCompiledBindingsByDefault=true`** — 每个 `x:DataType` 必须写（根 + 每个 DataTemplate），类型错误直接编译失败（好事）。
- 图标：`{x:Static assets:AppIcons.名称}`（`Assets/AppIcons.cs`），不要在 xaml 里写死几何。
- 主题：SukiUI DynamicResources（`SukiPrimaryColor*`、`SukiCardBackground`、`SukiLightBorderBrush`、`SukiDangerColor` 等）—— 桌面与 Android 通用；**Android 禁止 SukiWindow/SukiSideMenu**（SukiUI 桌面专用）。
- 控件 code-behind 极薄：只有 `InitializeComponent()`；逻辑走 VM 命令。

## DI（`App.axaml.cs` `ConfigureServices()`）

- Core 全套：`ITodoRepositoryService→TodoRepoService`、`ITodoService→TodoService`、`HttpClient`、`IRemoteServerSettingsRepository→RemoteServerSettingsService`、`IRemoteSyncService→RemoteSyncService`（全 Singleton）。
- 页面 VM：`TodoPageViewModel`（Core）、`SettingsPageViewModel`、`TalkViewModel`（Core）、`MainViewModel`（本目录）全 Singleton。
- 生命周期：桌面 → `MainWindow`；移动/单视图 → `MainView`。**启动同步即发即忘、关闭冲刷尽力而为**，绝不在 UI 线程阻塞于网络（`IRemoteSyncService.FlushAsync` 契约「绝不抛异常」）。
- 新 VM 记得在此注册，且保持 `XxxViewModel`/`XxxView` 成对平行命名空间（见 ViewLocator 节）。

## ANTI-PATTERNS

- 在共享项目里写平台专属代码（`SukiWindow` 之外的桌面 API、Android 专属控件）— 破坏四平台复用。
- 把字体放错目录 — `MashiruDaily.csproj` 只 `<AvaloniaResource Include="Assets\**"/>` 自动内嵌 `Assets/` 下的资源；`.axaml` 由 Avalonia SDK 按项目内路径隐式编译，但**别放 `Assets/` 下**（那里只放资源不放电声明）。
- 修改 `App.axaml.cs` 的启动/关闭流程时加 `await` 网络调用 — 违反「不得阻塞 UI 于网络」。
- 忘记 `x:DataType` / 用非 `{x:Static}` 的硬编码图标 — 编译失败或主题漂移。

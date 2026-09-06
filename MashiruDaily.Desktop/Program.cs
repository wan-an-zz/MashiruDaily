using System;
using Avalonia;
using MashiruDaily.Assets;

namespace MashiruDaily.Desktop;

sealed class Program
{
    // 初始化代码。在 AppMain 被调用前不要使用任何 Avalonia、第三方 API 或依赖
    // SynchronizationContext 的代码：此时尚未初始化，可能会出问题。
    [STAThread]
    public static void Main(string[] args) => BuildAvaloniaApp()
        .StartWithClassicDesktopLifetime(args);

    // Avalonia 配置，请勿删除；可视化设计器也会用到。
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
#if DEBUG
            .WithDeveloperTools()
#endif
            // 选项必须在 ConfigureFonts 创建 FontManager 之前绑定。
            .With(AppFonts.CreateFontManagerOptions())
            .ConfigureFonts(fontManager => fontManager.AddFontCollection(new NotoSansSCFontCollection()))
            .WithInterFont()
            .LogToTrace();
}

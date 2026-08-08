using System;
using Avalonia;
using MashiruDaily.Assets;

namespace MashiruDaily.Desktop;

sealed class Program
{
    // Initialization code. Don't use any Avalonia, third-party APIs or any
    // SynchronizationContext-reliant code before AppMain is called: things aren't initialized
    // yet and stuff might break.
    [STAThread]
    public static void Main(string[] args) => BuildAvaloniaApp()
        .StartWithClassicDesktopLifetime(args);

    // Avalonia configuration, don't remove; also used by visual designer.
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
#if DEBUG
            .WithDeveloperTools()
#endif
            // Options must be bound before ConfigureFonts creates the FontManager.
            .With(AppFonts.CreateFontManagerOptions())
            .ConfigureFonts(fontManager => fontManager.AddFontCollection(new NotoSansSCFontCollection()))
            .WithInterFont()
            .LogToTrace();
}

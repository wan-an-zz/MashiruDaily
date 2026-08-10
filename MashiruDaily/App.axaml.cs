using System;
using System.Net.Http;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Media;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Logging;
using MashiruDaily.Core.Services;
using MashiruDaily.Core.ViewModels.Todo;
using MashiruDaily.ViewModels;
using MashiruDaily.Views;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using NLog.Extensions.Logging;

namespace MashiruDaily;

public partial class App : Application
{
    /// <summary>Root dependency injection container.</summary>
    public static IServiceProvider Services { get; private set; } = null!;
    private bool _isDrainingShutdown;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override async void OnFrameworkInitializationCompleted()
    {
        Services = ConfigureServices();

        var todoService = Services.GetRequiredService<ITodoService>();
        await todoService.InitializeAsync();

        var logger = Services.GetRequiredService<ILogger<App>>();

        // Fire-and-forget Hermes startup sync; never block UI startup on the network.
        _ = SyncStartupAsync(Services.GetRequiredService<IHermesSyncService>(), logger);
        logger.LogInformation("MashiruDaily starting (desktop={IsDesktop}).",
            ApplicationLifetime is IClassicDesktopStyleApplicationLifetime);

        LogCjkFontResolution(logger);

        var mainViewModel = Services.GetRequiredService<MainViewModel>();
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.ShutdownRequested += OnShutdownRequested;
            desktop.MainWindow = new MainWindow { DataContext = mainViewModel };
        }
        else if (ApplicationLifetime is IActivityApplicationLifetime activityLifetime)
        {
            activityLifetime.MainViewFactory = () => new MainView { DataContext = mainViewModel };
        }
        else if (ApplicationLifetime is ISingleViewApplicationLifetime singleViewPlatform)
        {
            singleViewPlatform.MainView = new MainView { DataContext = mainViewModel };
        }

        base.OnFrameworkInitializationCompleted();
    }

    private async void OnShutdownRequested(object? sender, ShutdownRequestedEventArgs e)
    {
        if (_isDrainingShutdown)
            return;

        _isDrainingShutdown = true;
        e.Cancel = true;
        var todoService = Services.GetRequiredService<ITodoService>();
        await todoService.FlushAsync();

        // Best-effort drain of pending Hermes webhook events on exit; never block shutdown.
        try
        {
            await Services.GetRequiredService<IHermesSyncService>().FlushAsync();
        }
        catch (Exception ex)
        {
            Services.GetRequiredService<ILogger<App>>()
                .LogError(ex, "Hermes sync flush on shutdown failed.");
        }

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            desktop.Shutdown();
    }

    private static async Task SyncStartupAsync(IHermesSyncService sync, ILogger logger)
    {
        try
        {
            await sync.InitializeAsync();
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Hermes sync initialization failed.");
        }
    }

    private static void LogCjkFontResolution(ILogger logger)
    {
        // Diagnostic: report which font actually provides CJK glyphs. '待' = U+5F85.
        if (FontManager.Current.TryMatchCharacter(
                '待', FontStyle.Normal, FontWeight.Normal, FontStretch.Normal,
                FontFamily.Default, null, out var typeface))
        {
            logger.LogInformation("CJK glyph '待' resolved to font '{Font}'.", typeface.FontFamily.Name);
        }
        else
        {
            logger.LogWarning("CJK glyph '待' could not be resolved to any font.");
        }
    }

    private static IServiceProvider ConfigureServices()
    {
        var services = new ServiceCollection();

        services.AddLogging(builder =>
        {
            builder.ClearProviders();
            builder.AddNLog();
            LoggingConfigurator.Configure();
        });

        // Domain / infrastructure
        services.AddSingleton<ITodoRepository, JsonTodoRepository>();
        services.AddSingleton<ITodoService, TodoService>();

        // Hermes sync
        services.AddSingleton<HttpClient>();
        services.AddSingleton<IHermesSettingsRepository, JsonHermesSettingsRepository>();
        services.AddSingleton<IHermesSyncService, HermesSyncService>();

        // View models
        services.AddSingleton<TodoPageViewModel>();
        services.AddSingleton<SettingsPageViewModel>();
        services.AddSingleton<MainViewModel>();

        return services.BuildServiceProvider();
    }
}

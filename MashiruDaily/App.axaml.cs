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
    private bool _isDrainingShutdown;

    /// <summary>根依赖注入容器。</summary>
    public static IServiceProvider Services { get; private set; } = null!;

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

        // 即发即忘的 Hermes 启动同步；绝不在启动时阻塞 UI 于网络请求。
        _ = SyncStartupAsync(Services.GetRequiredService<IHermesSyncService>(), logger);
        logger.LogInformation("MashiruDaily 启动中（桌面={IsDesktop}）。",
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

        // 退出时尽力排空待处理的 Hermes Webhook 事件；绝不在关闭时阻塞。
        try
        {
            await Services.GetRequiredService<IHermesSyncService>().FlushAsync();
        }
        catch (Exception ex)
        {
            Services.GetRequiredService<ILogger<App>>()
                .LogError(ex, "关闭时的 Hermes 同步冲刷失败。");
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
            logger.LogError(ex, "Hermes 同步初始化失败。");
        }
    }

    private static void LogCjkFontResolution(ILogger logger)
    {
        // 诊断：报告实际提供 CJK 字形的是哪个字体。'待' = U+5F85。
        if (FontManager.Current.TryMatchCharacter(
                '待', FontStyle.Normal, FontWeight.Normal, FontStretch.Normal,
                FontFamily.Default, null, out var typeface))
        {
            logger.LogInformation("CJK 字形 '待' 由字体 '{Font}' 提供。", typeface.FontFamily.Name);
        }
        else
        {
            logger.LogWarning("CJK 字形 '待' 未能由任何字体提供。");
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

        // 领域 / 基础设施
        services.AddSingleton<ITodoRepository, JsonTodoRepository>();
        services.AddSingleton<ITodoService, TodoService>();

        // Hermes 同步
        services.AddSingleton<HttpClient>();
        services.AddSingleton<IHermesSettingsRepository, JsonHermesSettingsRepository>();
        services.AddSingleton<IHermesSyncService, HermesSyncService>();

        // 视图模型
        services.AddSingleton<TodoPageViewModel>();
        services.AddSingleton<SettingsPageViewModel>();
        services.AddSingleton<MainViewModel>();

        return services.BuildServiceProvider();
    }
}

using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Logging;
using MashiruDaily.Core.Services;
using MashiruDaily.Core.ViewModels;
using MashiruDaily.Core.ViewModels.Todo;
using MashiruDaily.Tui.Views;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using NLog.Extensions.Logging;
using Terminal.Gui.App;
using Terminal.Gui.Configuration;

ConfigurationManager.Enable(ConfigLocations.All);

var services = ConfigureServices();
var todoService = services.GetRequiredService<ITodoService>();
await todoService.InitializeAsync();

var sync = services.GetRequiredService<IRemoteSyncService>();
var logger = services.GetRequiredService<ILogger<Program>>();
sync.StatusChanged += (_, _) => logger.LogInformation("同步状态：{Status}", sync.Status);
_ = SyncStartupAsync(sync, logger);

var viewModel = services.GetRequiredService<TodoPageViewModel>();

var talkViewModel = services.GetRequiredService<TalkViewModel>();

IApplication app = Application.Create();
app.Init();
try
{
    app.Run(new MainWindow(viewModel, talkViewModel));
}
finally
{
    await todoService.FlushAsync();
    try { await sync.FlushAsync(); }
    catch (Exception ex) { logger.LogError(ex, "Hermes 同步冲刷失败。"); }
    app.Dispose();
}

static ServiceProvider ConfigureServices()
{
    var services = new ServiceCollection();

    services.AddLogging(builder =>
    {
        builder.ClearProviders();
        builder.AddNLog();
        // 控制台已被 Terminal.Gui 占用，日志输出到 stdout 会覆盖 TUI，只保留文件日志。
        LoggingConfigurator.Configure(consoleEnabled: false);
    });

    services.AddSingleton<HttpClient>();
    services.AddSingleton<ITodoRepositoryService, TodoRepoService>();
    services.AddSingleton<ITodoService, TodoService>();
    services.AddSingleton<IRemoteServerSettingsRepository, RemoteServerSettingsService>();
    services.AddSingleton<IRemoteSyncService, RemoteSyncService>();
    services.AddSingleton<TodoPageViewModel>();
    services.AddSingleton<TalkViewModel>();

    return services.BuildServiceProvider();
}

static async Task SyncStartupAsync(IRemoteSyncService sync, ILogger logger)
{
    try { await sync.InitializeAsync(); }
    catch (Exception ex) { logger.LogError(ex, "Hermes 同步初始化失败。"); }
}

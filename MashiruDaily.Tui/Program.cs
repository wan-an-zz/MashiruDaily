using MashiruDaily.Abstracts;
using MashiruDaily.Logging;
using MashiruDaily.Services;
using MashiruDaily.Tui.Views;
using MashiruDaily.ViewModels.Todo;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using NLog.Extensions.Logging;
using Terminal.Gui.App;
using Terminal.Gui.Configuration;

ConfigurationManager.Enable(ConfigLocations.All);

var services = ConfigureServices();
var todoService = services.GetRequiredService<ITodoService>();
await todoService.InitializeAsync();

var viewModel = services.GetRequiredService<TodoPageViewModel>();

IApplication app = Application.Create();
app.Init();
try
{
    app.Run(new MainWindow(viewModel));
}
finally
{
    await todoService.FlushAsync();
    app.Dispose();
}

static ServiceProvider ConfigureServices()
{
    var services = new ServiceCollection();

    services.AddLogging(builder =>
    {
        builder.ClearProviders();
        builder.AddNLog();
        LoggingConfigurator.Configure();
    });

    services.AddSingleton<ITodoRepository, JsonTodoRepository>();
    services.AddSingleton<ITodoService, TodoService>();
    services.AddSingleton<TodoPageViewModel>();

    return services.BuildServiceProvider();
}

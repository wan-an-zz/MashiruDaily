using System;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using MashiruDaily.Abstracts;
using MashiruDaily.Logging;
using MashiruDaily.Services;
using MashiruDaily.ViewModels;
using MashiruDaily.ViewModels.Todo;
using MashiruDaily.Views;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using NLog.Extensions.Logging;

namespace MashiruDaily;

public partial class App : Application
{
    /// <summary>Root dependency injection container.</summary>
    public static IServiceProvider Services { get; private set; } = null!;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        Services = ConfigureServices();

        var logger = Services.GetRequiredService<ILogger<App>>();
        logger.LogInformation("MashiruDaily starting (desktop={IsDesktop}).",
            ApplicationLifetime is IClassicDesktopStyleApplicationLifetime);

        var mainViewModel = Services.GetRequiredService<MainViewModel>();

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
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
        services.AddSingleton<ITodoRepository, InMemoryTodoRepository>();
        services.AddSingleton<ITodoService, TodoService>();

        // View models
        services.AddSingleton<TodoPageViewModel>();
        services.AddSingleton<MainViewModel>();

        return services.BuildServiceProvider();
    }
}

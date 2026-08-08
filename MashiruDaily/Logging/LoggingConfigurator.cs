using System;
using System.IO;
using NLog;
using NLog.Config;
using NLog.Targets;

namespace MashiruDaily.Logging;

/// <summary>
/// Configures NLog programmatically so it works on every platform
/// (desktop, Android, ...) without relying on a nlog.config file.
/// </summary>
public static class LoggingConfigurator
{
    public static void Configure()
    {
        var configuration = new LoggingConfiguration();

        configuration.AddRuleForAllLevels(new ConsoleTarget("console")
        {
            Layout = "${longdate}|${level:uppercase=true}|${logger}|${message}${onexception:|${exception:format=tostring}}"
        });

        var logDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "MashiruDaily", "logs");
        Directory.CreateDirectory(logDirectory);

        configuration.AddRuleForAllLevels(new FileTarget("file")
        {
            FileName = Path.Combine(logDirectory, "mashiru-${shortdate}.log"),
            Layout = "${longdate}|${level:uppercase=true}|${logger}|${message}${onexception:|${exception:format=tostring}}",
            KeepFileOpen = false,
            ArchiveAboveSize = 10 * 1024 * 1024,
            MaxArchiveFiles = 5,
        });

        LogManager.Configuration = configuration;
    }
}

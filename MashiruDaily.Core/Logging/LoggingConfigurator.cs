using System;
using System.IO;
using NLog;
using NLog.Config;
using NLog.Targets;

namespace MashiruDaily.Core.Logging;

/// <summary>
/// 以编程方式配置 NLog，使它在每个平台（桌面、Android 等）都能工作，
/// 无需依赖 nlog.config 文件。
/// </summary>
public static class LoggingConfigurator
{
    /// <param name="consoleEnabled">
    /// 是否输出到控制台。TUI 场景下传入 false。
    /// </param>
    public static void Configure(bool consoleEnabled = true)
    {
        var configuration = new LoggingConfiguration();

        if (consoleEnabled)
        {
            configuration.AddRuleForAllLevels(new ConsoleTarget("console")
            {
                Layout = "${longdate}|${level:uppercase=true}|${logger}|${message}${onexception:|${exception:format=tostring}}"
            });
        }

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

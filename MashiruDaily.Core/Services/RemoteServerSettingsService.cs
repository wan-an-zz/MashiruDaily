using System;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// 将 Hermes AI 同步设置以单个 JSON 对象持久化到
/// <c>%APPDATA%\MashiruDaily\settings.json</c>。
/// 写入是原子的（tmp 文件 + move），崩溃不会留下半写的文件。
/// 缺失或损坏的文件按 <see cref="RemoteServerSettings.CreateDefault"/> 加载；
/// IO 失败只记录日志，绝不抛出。
/// </summary>
public sealed class RemoteServerSettingsService : IRemoteServerSettingsRepository
{
    private readonly ILogger<RemoteServerSettingsService> _logger;

    private readonly string _directory;

    private readonly string _filePath;

    public RemoteServerSettingsService(ILogger<RemoteServerSettingsService> logger, string? dataDirectory = null)
    {
        _logger = logger;
        _directory = dataDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "MashiruDaily");
        _filePath = Path.Combine(_directory, "settings.json");
    }

    public Task<RemoteServerSettings> LoadAsync()
    {
        try
        {
            if (!File.Exists(_filePath))
                return Task.FromResult(RemoteServerSettings.CreateDefault());

            var json = File.ReadAllText(_filePath);
            var settings = JsonSerializer.Deserialize<RemoteServerSettings>(json);
            return Task.FromResult(settings ?? RemoteServerSettings.CreateDefault());
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "从 '{File}' 加载 Hermes 设置失败；改用默认值。", _filePath);
            return Task.FromResult(RemoteServerSettings.CreateDefault());
        }
    }

    public async Task SaveAsync(RemoteServerSettings settings)
    {
        try
        {
            Directory.CreateDirectory(_directory);
            var json = JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true });
            var tmp = _filePath + ".tmp";
            await File.WriteAllTextAsync(tmp, json);
            File.Move(tmp, _filePath, overwrite: true);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "保存 Hermes 设置到 '{File}' 失败。", _filePath);
        }
    }
}

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
/// 缺失或损坏的文件按 <see cref="HermesSettings.CreateDefault"/> 加载；
/// IO 失败只记录日志，绝不抛出。
/// </summary>
public sealed class JsonHermesSettingsRepository : IHermesSettingsRepository
{
    private readonly ILogger<JsonHermesSettingsRepository> _logger;

    private readonly string _directory;

    private readonly string _filePath;

    public JsonHermesSettingsRepository(ILogger<JsonHermesSettingsRepository> logger, string? dataDirectory = null)
    {
        _logger = logger;
        _directory = dataDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "MashiruDaily");
        _filePath = Path.Combine(_directory, "settings.json");
    }

    public Task<HermesSettings> LoadAsync()
    {
        try
        {
            if (!File.Exists(_filePath))
                return Task.FromResult(HermesSettings.CreateDefault());

            var json = File.ReadAllText(_filePath);
            var settings = JsonSerializer.Deserialize<HermesSettings>(json);
            return Task.FromResult(settings ?? HermesSettings.CreateDefault());
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "从 '{File}' 加载 Hermes 设置失败；改用默认值。", _filePath);
            return Task.FromResult(HermesSettings.CreateDefault());
        }
    }

    public async Task SaveAsync(HermesSettings settings)
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

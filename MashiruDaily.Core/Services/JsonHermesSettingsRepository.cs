using System;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using MashiruDaily.Abstracts;
using MashiruDaily.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Services;

/// <summary>
/// Persists Hermes AI-sync settings as a single JSON object under
/// <c>%APPDATA%\MashiruDaily\settings.json</c>.
/// Writes are atomic (tmp file + move) so a crash never leaves a half-written file.
/// Missing or corrupt files load as <see cref="HermesSettings.CreateDefault"/>;
/// IO failures are logged, never thrown.
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
            _logger.LogError(ex, "Failed to load Hermes settings from '{File}'; using defaults.", _filePath);
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
            _logger.LogError(ex, "Failed to save Hermes settings to '{File}'.", _filePath);
        }
    }
}

using System;
using System.IO;
using System.Threading.Tasks;
using MashiruDaily.Models;
using MashiruDaily.Services;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace MashiruDaily.Tests;

public class JsonHermesSettingsRepositoryTests : IDisposable
{
    private readonly string _dir;
    private readonly string _file;
    private readonly JsonHermesSettingsRepository _repository;

    public JsonHermesSettingsRepositoryTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "MashiruDaily.Tests", Guid.NewGuid().ToString("N"));
        _file = Path.Combine(_dir, "settings.json");
        _repository = new JsonHermesSettingsRepository(NullLogger<JsonHermesSettingsRepository>.Instance, _dir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
            Directory.Delete(_dir, recursive: true);
    }

    [Fact]
    public async Task RoundTrip_PreservesAllFields()
    {
        var settings = new HermesSettings
        {
            ServerBaseUrl = "http://192.168.1.100:8080",
            HermesBaseUrl = "http://10.0.0.5:8644",
            WebhookRouteName = "custom-sync",
            WebhookSecret = "s3cret-hmac-key",
            SyncEnabled = true,
            MaxRetryAttempts = 7,
            TimeoutSeconds = 25.5,
            LastSyncedDate = "2026-08-09",
        };

        await _repository.SaveAsync(settings);
        var loaded = await _repository.LoadAsync();

        Assert.Equal(settings.ServerBaseUrl, loaded.ServerBaseUrl);
        Assert.Equal(settings.HermesBaseUrl, loaded.HermesBaseUrl);
        Assert.Equal(settings.WebhookRouteName, loaded.WebhookRouteName);
        Assert.Equal(settings.WebhookSecret, loaded.WebhookSecret);
        Assert.Equal(settings.SyncEnabled, loaded.SyncEnabled);
        Assert.Equal(settings.MaxRetryAttempts, loaded.MaxRetryAttempts);
        Assert.Equal(settings.TimeoutSeconds, loaded.TimeoutSeconds);
        Assert.Equal(settings.LastSyncedDate, loaded.LastSyncedDate);
    }

    [Fact]
    public async Task LoadAsync_WhenFileMissing_ReturnsDefaults()
    {
        var loaded = await _repository.LoadAsync();

        Assert.Equal(string.Empty, loaded.ServerBaseUrl);
        Assert.Equal("http://localhost:8644", loaded.HermesBaseUrl);
        Assert.Equal("todo-sync", loaded.WebhookRouteName);
        Assert.Equal(string.Empty, loaded.WebhookSecret);
        Assert.False(loaded.SyncEnabled);
        Assert.Equal(3, loaded.MaxRetryAttempts);
        Assert.Equal(10, loaded.TimeoutSeconds);
        Assert.Null(loaded.LastSyncedDate);
    }

    [Fact]
    public async Task LoadAsync_WhenFileCorrupt_ReturnsDefaultsAndDoesNotThrow()
    {
        Directory.CreateDirectory(_dir);
        await File.WriteAllTextAsync(_file, "{ not valid json !!!");

        var loaded = await _repository.LoadAsync();

        Assert.False(loaded.SyncEnabled);
        Assert.Equal(3, loaded.MaxRetryAttempts);
        Assert.Equal("http://localhost:8644", loaded.HermesBaseUrl);
    }

    [Fact]
    public async Task SaveAsync_CreatesDirectoryAndWritesAtomicFile()
    {
        await _repository.SaveAsync(HermesSettings.CreateDefault());

        Assert.True(File.Exists(_file));
        Assert.False(File.Exists(_file + ".tmp"));
    }
}

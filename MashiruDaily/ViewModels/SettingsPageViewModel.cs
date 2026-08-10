using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;
using MashiruDaily.Core.ViewModels;

namespace MashiruDaily.ViewModels;

public partial class SettingsPageViewModel : ViewModelBase
{
    private readonly IHermesSettingsRepository _settingsRepository;

    private readonly IHermesSyncService _syncService;

    private readonly HttpClient _httpClient;

    [ObservableProperty]
    private string _serverBaseUrl = string.Empty;

    [ObservableProperty]
    private string _hermesBaseUrl = string.Empty;

    [ObservableProperty]
    private string _webhookRouteName = string.Empty;

    [ObservableProperty]
    private string _webhookSecret = string.Empty;

    [ObservableProperty]
    private int _maxRetryAttempts;

    [ObservableProperty]
    private double _timeoutSeconds;

    [ObservableProperty]
    private bool _syncEnabled;

    [ObservableProperty]
    private string? _errorText;

    [ObservableProperty]
    private string? _infoText;

    [ObservableProperty]
    private string _syncStatusText = "空闲";

    [ObservableProperty]
    private bool _hasSyncError;

    [ObservableProperty]
    private string? _testResultText;

    public SettingsPageViewModel(
        IHermesSettingsRepository settingsRepository,
        IHermesSyncService syncService,
        HttpClient httpClient)
    {
        _settingsRepository = settingsRepository;
        _syncService = syncService;
        _httpClient = httpClient;
        _ = LoadSettingsAsync();
        _syncService.StatusChanged += OnSyncStatusChanged;
        UpdateSyncStatus();
    }

    private async Task LoadSettingsAsync()
    {
        var settings = await _settingsRepository.LoadAsync();
        ServerBaseUrl = settings.ServerBaseUrl;
        HermesBaseUrl = settings.HermesBaseUrl;
        WebhookRouteName = settings.WebhookRouteName;
        WebhookSecret = settings.WebhookSecret;
        MaxRetryAttempts = settings.MaxRetryAttempts;
        TimeoutSeconds = settings.TimeoutSeconds;
        SyncEnabled = settings.SyncEnabled;
    }

    [RelayCommand]
    private async Task Save()
    {
        ErrorText = Validate();
        InfoText = null;
        if (ErrorText is not null)
            return;

        await _settingsRepository.SaveAsync(new HermesSettings
        {
            ServerBaseUrl = ServerBaseUrl.Trim(),
            HermesBaseUrl = HermesBaseUrl.Trim(),
            WebhookRouteName = WebhookRouteName.Trim(),
            WebhookSecret = WebhookSecret,
            MaxRetryAttempts = MaxRetryAttempts,
            TimeoutSeconds = TimeoutSeconds,
            SyncEnabled = SyncEnabled,
        });
        ErrorText = null;
        InfoText = "设置已保存";
    }

    private string? Validate()
    {
        if (!SyncEnabled)
            return null;
        if (string.IsNullOrWhiteSpace(ServerBaseUrl)) return "服务器地址不能为空";
        if (string.IsNullOrWhiteSpace(HermesBaseUrl)) return "Hermes 地址不能为空";
        if (string.IsNullOrWhiteSpace(WebhookSecret)) return "Webhook 密钥不能为空";
        if (MaxRetryAttempts < 1) return "最大重试次数必须至少为 1";
        if (TimeoutSeconds <= 0) return "超时秒数必须大于 0";
        return null;
    }

    [RelayCommand]
    private async Task TestConnection()
    {
        TestResultText = null;
        HasSyncError = false;
        try
        {
            var baseUrl = HermesBaseUrl.TrimEnd('/');
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var response = await _httpClient.GetAsync($"{baseUrl}/health", timeout.Token);
            TestResultText = response.IsSuccessStatusCode
                ? "连接正常"
                : $"连接失败: {(int)response.StatusCode}";
            HasSyncError = !response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            TestResultText = $"连接失败: {ex.Message}";
            HasSyncError = true;
        }
    }

    [RelayCommand]
    private Task SyncNow() => _syncService.SyncNowAsync();

    private void OnSyncStatusChanged(object? sender, EventArgs e) =>
        Dispatcher.UIThread.Post(UpdateSyncStatus);

    private void UpdateSyncStatus()
    {
        SyncStatusText = _syncService.Status switch
        {
            SyncStatus.Idle => "空闲",
            SyncStatus.Syncing => "同步中",
            SyncStatus.Pulling => "拉取中",
            SyncStatus.Success => "已同步",
            SyncStatus.Error => "同步失败",
            SyncStatus.Skipped => "已跳过",
            _ => "空闲",
        };
        HasSyncError = _syncService.Status == SyncStatus.Error;
        if (HasSyncError)
            ErrorText = _syncService.LastError;
    }
}

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Converters;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// Hermes AI 同步后台任务。监听 <see cref="ITodoService"/> 的变更，
/// 将变更作为已签名的 Webhook 事件推送到 Hermes，并实现通信协议中定义的
/// 启动「先比对服务器创建时间，再决定推拉」流程。维护最近观测数据的值快照，
/// 以便在不动 <c>TodoService</c> 自身锁的情况下做差异对比。
/// </summary>
public sealed partial class HermesSyncService : ObservableObject, IHermesSyncService
{
    private static class EventTypes
    {
        public const string Added = "todo_added";

        public const string Updated = "todo_updated";

        public const string Completed = "todo_completed";

        public const string Reopened = "todo_reopened";

        public const string Deleted = "todo_deleted";
    }

    private sealed record PendingEvent(TodoItem Snapshot, string Type);

    /// <summary>
    /// 拉取决策：是否需要拉取，以及服务器 todo.json 的创建时间（UTC）。
    /// </summary>
    private sealed record MetaResult(bool NeedPull, DateTimeOffset ServerCreatedAt);

    private sealed class MetaDate
    {
        public string? Date { get; set; }

        public string? CreatedAt { get; set; }
    }

    private static readonly JsonSerializerOptions SnakeCaseOption = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new LocalDateTimeJsonConverter() }
    };

    private readonly ITodoService _todoService;

    private readonly IHermesSettingsRepository _settingsRepo;

    private readonly ILogger<HermesSyncService> _logger;

    private readonly HttpClient _httpClient;

    private readonly Guid _clientId = Guid.NewGuid();

    private readonly SemaphoreSlim _gate = new(1, 1);

    private readonly object _stateLock = new();

    private readonly Dictionary<Guid, TodoItem> _snapshot = new();

    private readonly Queue<PendingEvent> _pendingQueue = new();

    private volatile bool _suppressChanged;

    private volatile bool _initialized;

    private int _dispatchRunning;

    private HermesSettings _settings = HermesSettings.CreateDefault();

    [ObservableProperty]
    private SyncStatus _status;

    [ObservableProperty]
    private string? _lastError;

    [ObservableProperty]
    private int _pendingSyncCount;

    /// <inheritdoc />
    public event EventHandler? StatusChanged;

    /// <summary>
    /// 创建同步服务。订阅 <see cref="ITodoService.Changed"/>，
    /// 以便自动对比并推送后续变更。
    /// </summary>
    /// <param name="todoService">待办数据的唯一来源，必须先初始化。</param>
    /// <param name="settingsRepo">持久化的 Hermes 设置存储。</param>
    /// <param name="logger">结构化日志器。</param>
    /// <param name="httpClient">可选客户端（测试用）；缺省时创建默认实例。</param>
    public HermesSyncService(
        ITodoService todoService,
        IHermesSettingsRepository settingsRepo,
        ILogger<HermesSyncService> logger,
        HttpClient? httpClient = null)
    {
        _todoService = todoService;
        _settingsRepo = settingsRepo;
        _logger = logger;
        _httpClient = httpClient ?? new HttpClient();
        _todoService.Changed += OnServiceChanged;
    }

    /// <inheritdoc />
    public async Task InitializeAsync()
    {
        await _gate.WaitAsync();
        try
        {
            await InitializeCoreAsync();
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc />
    public async Task SyncNowAsync()
    {
        try
        {
            await _gate.WaitAsync();
            try
            {
                if (!_initialized)
                {
                    await InitializeCoreAsync();
                    return;
                }

                if (!_settings.SyncEnabled)
                    return;

                _logger.LogInformation("手动同步已请求");
                var meta = await FetchMetaAsync();
                if (meta is null)
                    return;
                if (meta.NeedPull)
                {
                    await PullTodoListAsync(meta.ServerCreatedAt);
                    return;
                }

                await PushPendingOnlyAsync();
            }
            finally
            {
                _gate.Release();
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Hermes 手动同步失败。");
            UpdateStatus(SyncStatus.Error, ex.Message);
        }
    }

    /// <inheritdoc />
    public async Task FlushAsync()
    {
        try
        {
            await _gate.WaitAsync();
            try
            {
                if (!_initialized || !_settings.SyncEnabled)
                    return;

                _logger.LogInformation("正在冲刷待处理的 Hermes 事件。");
                EnqueuePendingAsUpdated();
                await DispatchCoreAsync();
            }
            finally
            {
                _gate.Release();
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Hermes 冲刷失败。");
        }
    }

    private async Task InitializeCoreAsync()
    {
        if (_initialized)
            return;

        try
        {
            _settings = await _settingsRepo.LoadAsync();
            _httpClient.Timeout = TimeSpan.FromSeconds(Math.Max(1, _settings.TimeoutSeconds));

            lock (_stateLock)
            {
                _snapshot.Clear();
                foreach (var item in _todoService.Items)
                    _snapshot[item.Id] = Copy(item);
            }

            _initialized = true;

            if (!_settings.SyncEnabled)
            {
                _logger.LogInformation("Hermes 同步已禁用；跳过初始化网络调用。");
                UpdateStatus(SyncStatus.Idle, null);
                return;
            }

            _logger.LogInformation("Hermes 同步已启用：先比对服务器创建时间，再决定推拉。");
            var meta = await FetchMetaAsync();
            if (meta is null)
                return;
            if (meta.NeedPull)
            {
                await PullTodoListAsync(meta.ServerCreatedAt);
                return;
            }

            await PushPendingOnlyAsync();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Hermes 同步初始化失败。");
            UpdateStatus(SyncStatus.Error, ex.Message);
        }
    }

    private void OnServiceChanged(object? sender, EventArgs e)
    {
        // 只做差异对比并入队（快速、无 I/O）；由后台分发循环消费队列。
        if (_suppressChanged || !_initialized || !_settings.SyncEnabled)
            return;

        if (DiffAndEnqueue() > 0)
        {
            RefreshPendingSyncCount();
            _ = DispatchPendingAsync();
        }
    }

    /// <summary>
    /// 将当前条目与快照对比，每个变更入队一个事件。
    /// </summary>
    /// <returns>入队的事件数量。</returns>
    private int DiffAndEnqueue()
    {
        var live = _todoService.Items;
        int enqueued = 0;
        var liveIds = new HashSet<Guid>(live.Count);

        lock (_stateLock)
        {
            foreach (var item in live)
            {
                liveIds.Add(item.Id);
                if (_snapshot.TryGetValue(item.Id, out var previous))
                {
                    if (previous.IsCompleted != item.IsCompleted)
                    {
                        EnqueueLocked(Copy(item),
                            item.IsCompleted ? EventTypes.Completed : EventTypes.Reopened);
                        enqueued++;
                    }
                    else if (!string.Equals(previous.Title, item.Title, StringComparison.Ordinal))
                    {
                        EnqueueLocked(Copy(item), EventTypes.Updated);
                        enqueued++;
                    }
                }
                else
                {
                    EnqueueLocked(Copy(item), EventTypes.Added);
                    enqueued++;
                }

                _snapshot[item.Id] = Copy(item);
            }

            foreach (var id in _snapshot.Keys.Where(k => !liveIds.Contains(k)).ToList())
            {
                EnqueueLocked(_snapshot[id], EventTypes.Deleted);
                _snapshot.Remove(id);
                enqueued++;
            }
        }

        return enqueued;
    }

    private void EnqueueLocked(TodoItem item, string eventType)
        => _pendingQueue.Enqueue(new PendingEvent(item, eventType));

    /// <summary>
    /// 将每个 <c>HasSynced == false</c> 的现存条目作为 <c>todo_updated</c>
    /// upsert 入队（用于启动、手动同步与关闭冲刷）。
    /// </summary>
    private void EnqueuePendingAsUpdated()
    {
        lock (_stateLock)
        {
            foreach (var item in _todoService.Items)
            {
                if (!item.HasSynced)
                    _pendingQueue.Enqueue(new PendingEvent(Copy(item), EventTypes.Updated));
            }
        }

        RefreshPendingSyncCount();
    }

    /// <summary>
    /// 即发即忘入口：保证只有一个排空循环在运行，
    /// 若在排空与守卫复位之间又有事件到达则自行重新触发。
    /// </summary>
    private async Task DispatchPendingAsync()
    {
        if (Interlocked.CompareExchange(ref _dispatchRunning, 1, 0) != 0)
            return;

        try
        {
            await _gate.WaitAsync();
            try
            {
                await DispatchCoreAsync();
            }
            finally
            {
                _gate.Release();
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Hermes 待处理事件分发失败。");
        }
        finally
        {
            Interlocked.Exchange(ref _dispatchRunning, 0);
        }

        if (HasPending())
            _ = DispatchPendingAsync();
    }

    /// <summary>
    /// 排空待处理队列，逐个发送事件（串行，限流安全）。
    /// 调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    private async Task DispatchCoreAsync()
    {
        while (true)
        {
            List<PendingEvent>? batch;
            lock (_stateLock)
            {
                if (_pendingQueue.Count == 0)
                    return;
                batch = new List<PendingEvent>(_pendingQueue);
                _pendingQueue.Clear();
            }

            foreach (var ev in batch)
            {
                try
                {
                    await SendAsync(ev.Snapshot, ev.Type);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "发送 {EventType} 事件给待办 {Id} 时出现意外错误。",
                        ev.Type, ev.Snapshot.Id);
                }
            }
        }
    }

    private bool HasPending()
    {
        lock (_stateLock)
        {
            return _pendingQueue.Count > 0;
        }
    }

    /// <summary>
    /// 发送一个已签名的 Webhook 事件，最多重试
    /// <see cref="HermesSettings.MaxRetryAttempts"/> + 1 次。
    /// 成功后将现存条目标记为已同步；全部失败则保持待处理。
    /// </summary>
    private async Task SendAsync(TodoItem item, string eventType)
    {
        var eventId = Guid.NewGuid();
        var envelope = new
        {
            eventType,
            clientId = _clientId,
            eventId,
            timestamp = DateTimeOffset.Now.ToString("O", CultureInfo.InvariantCulture),
            payload = new
            {
                id = item.Id,
                title = item.Title,
                isCompleted = item.IsCompleted,
                createdAt = item.CreatedAt,
                completedAt = item.CompletedAt,
            },
        };
        var rawBody = JsonSerializer.Serialize(envelope, SnakeCaseOption);
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
        var signature = HermesWebhookSigner.ComputeSignature(_settings.WebhookSecret, timestamp, rawBody);
        var url = $"{_settings.HermesBaseUrl.TrimEnd('/')}/webhooks/{_settings.WebhookRouteName}";

        var totalAttempts = Math.Max(0, _settings.MaxRetryAttempts) + 1;

        for (var attempt = 1; attempt <= totalAttempts; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, url);
                request.Content = new StringContent(rawBody, Encoding.UTF8, "application/json");
                request.Headers.TryAddWithoutValidation("X-Webhook-Timestamp", timestamp);
                request.Headers.TryAddWithoutValidation("X-Webhook-Signature-V2", signature);
                request.Headers.TryAddWithoutValidation("X-Request-ID", eventId.ToString());

                using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
                if (response.IsSuccessStatusCode)
                {
                    _logger.LogInformation(
                        "待办 {Id} 的 Webhook {EventType} 已被接受（HTTP {StatusCode}）。",
                        item.Id, eventType, (int)response.StatusCode);
                    await _todoService.MarkSyncedAsync(new[] { item.Id });
                    RefreshPendingSyncCount();
                    UpdateStatus(SyncStatus.Success, null);
                    return;
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    _logger.LogWarning(
                        "待办 {Id} 的 Webhook 被限流（429），退避等待（第 {Attempt}/{Total} 次尝试）。",
                        item.Id, attempt, totalAttempts);
                    if (attempt < totalAttempts)
                        await Task.Delay(TimeSpan.FromSeconds(2));
                    continue;
                }

                _logger.LogWarning(
                    "待办 {Id} 的 Webhook {EventType} 失败，HTTP {StatusCode}（第 {Attempt}/{Total} 次尝试）。",
                    item.Id, eventType, (int)response.StatusCode, attempt, totalAttempts);
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
            {
                _logger.LogWarning(
                    ex, "待办 {Id} 的 Webhook {EventType} 网络错误（第 {Attempt}/{Total} 次尝试）。",
                    item.Id, eventType, attempt, totalAttempts);
            }
        }

        _logger.LogError(
            "待办 {Id} 的 Webhook {EventType} 已用尽全部 {TotalAttempts} 次尝试；条目保持待处理。",
            item.Id, eventType, totalAttempts);
        UpdateStatus(SyncStatus.Error, $"待办 {item.Id} 的 Webhook {eventType} 在 {totalAttempts} 次尝试后失败。");
        RefreshPendingSyncCount();
    }

    /// <summary>
    /// 请求服务器元数据，并依据 <c>createdAt</c> 与本地 <see cref="HermesSettings.LastSyncedAt"/>
    /// 决定是否需要拉取。调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    /// <returns>
    /// 拉取决策与服务器 todo.json 的创建时间；失败时置 <see cref="SyncStatus.Error"/> 并返回 null。
    /// </returns>
    private async Task<MetaResult?> FetchMetaAsync()
    {
        UpdateStatus(SyncStatus.Pulling, null);

        var baseUrl = _settings.ServerBaseUrl.TrimEnd('/');
        var metaUrl = $"{baseUrl}/api/todo/meta";

        MetaDate? meta;
        try
        {
            using var metaResponse = await _httpClient.GetAsync(metaUrl);
            if (metaResponse.StatusCode != HttpStatusCode.OK)
            {
                UpdateStatus(SyncStatus.Error, $"元数据请求返回 HTTP {(int)metaResponse.StatusCode}。");
                return null;
            }

            meta = await metaResponse.Content.ReadFromJsonAsync<MetaDate>(SnakeCaseOption);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or NotSupportedException)
        {
            _logger.LogError(ex, "Hermes 元数据请求失败。");
            UpdateStatus(SyncStatus.Error, $"元数据请求失败：{ex.Message}");
            return null;
        }

        if (meta?.CreatedAt is not { Length: > 0 } createdAt
            || !DateTimeOffset.TryParse(createdAt, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal, out var parsed))
        {
            UpdateStatus(SyncStatus.Error, "元数据响应未包含有效的 createdAt。");
            return null;
        }

        var serverUtc = parsed.ToUniversalTime();

        bool needPull;
        if (string.IsNullOrWhiteSpace(_settings.LastSyncedAt))
        {
            needPull = true;
        }
        else if (!DateTimeOffset.TryParse(_settings.LastSyncedAt, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal, out var lastSyncedAt))
        {
            needPull = true;
        }
        else
        {
            needPull = serverUtc > lastSyncedAt;
        }

        return new MetaResult(needPull, serverUtc);
    }

    /// <summary>
    /// 拉取服务器整列表并整体替换本地集合，最后持久化
    /// <see cref="HermesSettings.LastSyncedAt"/> 为服务器创建时间。
    /// 调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    private async Task PullTodoListAsync(DateTimeOffset serverCreatedAt)
    {
        var baseUrl = _settings.ServerBaseUrl.TrimEnd('/');
        var listUrl = $"{baseUrl}/api/todo";

        List<TodoItem>? pulled;
        try
        {
            using var listResponse = await _httpClient.GetAsync(listUrl);
            if (listResponse.StatusCode != HttpStatusCode.OK)
            {
                UpdateStatus(SyncStatus.Error, $"待办列表请求返回 HTTP {(int)listResponse.StatusCode}。");
                return;
            }

            pulled = await listResponse.Content.ReadFromJsonAsync<List<TodoItem>>();
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or NotSupportedException)
        {
            _logger.LogError(ex, "Hermes 待办列表请求失败。");
            UpdateStatus(SyncStatus.Error, $"待办列表请求失败：{ex.Message}");
            return;
        }

        pulled ??= new List<TodoItem>();
        foreach (var item in pulled)
            item.HasSynced = true;

        _suppressChanged = true;
        try
        {
            await _todoService.ReplaceAllAsync(pulled);
        }
        finally
        {
            _suppressChanged = false;
        }

        lock (_stateLock)
        {
            _snapshot.Clear();
            foreach (var item in pulled)
                _snapshot[item.Id] = Copy(item);
        }

        _settings.LastSyncedAt = serverCreatedAt.UtcDateTime.ToString("O", CultureInfo.InvariantCulture);
        await _settingsRepo.SaveAsync(_settings);

        _logger.LogInformation("已从服务器拉取 {Count} 条待办；上次同步时间更新为 {CreatedAt}。",
            pulled.Count, _settings.LastSyncedAt);
        UpdateStatus(SyncStatus.Success, null);
        RefreshPendingSyncCount();
    }

    /// <summary>
    /// 服务器 todo.json 创建时间不晚于上次同步时：仅推送本地待处理项。
    /// 调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    private async Task PushPendingOnlyAsync()
    {
        _logger.LogInformation("服务器 todo.json 创建时间不晚于上次同步；推送本地待处理项。");
        EnqueuePendingAsUpdated();
        await DispatchCoreAsync();
        if (PendingSyncCount == 0)
            UpdateStatus(SyncStatus.Success, null);
    }

    private void RefreshPendingSyncCount()
    {
        int count = _todoService.Items.Count(x => !x.HasSynced);
        if (count != PendingSyncCount)
        {
            PendingSyncCount = count;
            StatusChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    private void UpdateStatus(SyncStatus newStatus, string? error)
    {
        if (Status == newStatus && LastError == error)
            return;

        Status = newStatus;
        LastError = error;
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    private static TodoItem Copy(TodoItem item) => new()
    {
        Id = item.Id,
        Title = item.Title,
        IsCompleted = item.IsCompleted,
        CreatedAt = item.CreatedAt,
        CompletedAt = item.CompletedAt,
    };
}

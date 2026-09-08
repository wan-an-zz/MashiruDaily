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
using System.Threading.Channels;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Converters;
using MashiruDaily.Core.Events;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// 远程同步后台任务。监听 <see cref="ITodoService"/> 的变更，
/// 将变更作为批量事件推送到服务器 /api/update，并执行启动时
/// 「先比对服务器更新时间，再决定拉取或推送」的流程。
/// 维护最近观测数据的值快照，用于在不动 <c>TodoService</c> 自身锁的情况下做差异对比。
/// </summary>
public sealed partial class RemoteSyncService : ObservableObject, IRemoteSyncService, IDisposable
{
    private static class EventTypes
    {
        public const string Added = "todo_added";

        public const string Updated = "todo_updated";

        public const string Completed = "todo_completed";

        public const string Reopened = "todo_reopened";

        public const string Deleted = "todo_deleted";
    }

    private sealed record WebhookSnapshot(
        string RawBody,
        string Timestamp,
        string Signature,
        string WebhookUrl,
        string MessagesUrl,
        string RequestId);

    private sealed record PendingEvent(TodoItem Snapshot, string Type);

    /// <summary>
    /// 拉取决策：是否需要拉取，以及服务器todo.json 的更新时间（统一 UTC+8）。
    /// </summary>
    private sealed record MetaResult(bool NeedPull, DateTimeOffset ServerUpdatedAt);

    private sealed class MetaDate
    {
        public string? Date { get; set; }

        public string? UpdatedAt { get; set; }
    }

    private static readonly JsonSerializerOptions SnakeCaseOption = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new LocalDateTimeJsonConverter() }
    };

    private readonly ITodoService _todoService;

    private readonly IRemoteServerSettingsRepository _settingsRepo;

    private readonly ILogger<RemoteSyncService> _logger;

    private readonly HttpClient _httpClient;

    private readonly SemaphoreSlim _gate = new(1, 1);

    private readonly object _stateLock = new();

    private readonly object _timerLock = new();

    private readonly Dictionary<Guid, TodoItem> _snapshot = new();

    private readonly Queue<PendingEvent> _pendingQueue = new();

    private volatile bool _suppressChanged;

    private volatile bool _initialized;

    private int _dispatchRunning;

    private RemoteServerSettings _settings = RemoteServerSettings.CreateDefault();

    private Timer? _timer;
    private readonly TimeSpan _agentReactionPollInterval;

    private readonly bool _webhookReactionEnabled;

    private readonly Channel<WebhookSnapshot> _channel = Channel.CreateUnbounded<WebhookSnapshot>();

    private readonly CancellationTokenSource _webhookCts = new();

    private readonly object _webhookWorkerLock = new();

    private Task? _webhookWorker;

    [ObservableProperty]
    private SyncStatus _status;

    [ObservableProperty]
    private string? _lastError;

    [ObservableProperty]
    private int _pendingSyncCount;

    /// <inheritdoc />
    public event EventHandler? StatusChanged;

    // <inheritdoc />
    public event EventHandler<GetMessageSuccessfulEventArgs>? GetMessageSuccessful;

    /// <summary>
    /// 创建同步服务。订阅 <see cref="ITodoService.Changed"/>，
    /// 以便自动对比并推送后续变更。
    /// </summary>
    /// <param name="todoService">待办数据的唯一来源，必须先初始化。</param>
    /// <param name="settingsRepo">远程同步设置存储。</param>
    /// <param name="logger">结构化日志器。</param>
    /// <param name="httpClient">可选客户端（测试用）；缺省时创建默认实例。</param>
    public RemoteSyncService(
        ITodoService todoService,
        IRemoteServerSettingsRepository settingsRepo,
        ILogger<RemoteSyncService> logger,
        HttpClient? httpClient = null,
        TimeSpan? agentReactionPollInterval = null,
        bool webhookReactionEnabled = true)
    {
        _todoService = todoService;
        _settingsRepo = settingsRepo;
        _logger = logger;
        _httpClient = httpClient ?? new HttpClient();
        _agentReactionPollInterval = agentReactionPollInterval ?? TimeSpan.FromSeconds(30);
        _webhookReactionEnabled = webhookReactionEnabled;
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
                    await PullTodoListAsync(meta.ServerUpdatedAt);
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
            _logger.LogError(ex, "远程手动同步失败。");
            UpdateStatus(SyncStatus.Error, ex.Message);
        }
    }

    /// <inheritdoc />
    public async Task ApplySettingsAsync(RemoteServerSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);

        await _gate.WaitAsync();
        try
        {
            // LastSyncedAt 是同步服务内部推进的同步水位，不是用户在设置页编辑的字段；
            // 保存设置时不能把它一起覆盖掉，否则会把“刚保存的配置”误判为需要全量拉取。
            var lastSyncedAt = _settings.LastSyncedAt;
            _settings = new RemoteServerSettings
            {
                ServerBaseUrl = settings.ServerBaseUrl,
                HermesBaseUrl = settings.HermesBaseUrl,
                WebhookRouteName = settings.WebhookRouteName,
                WebhookSecret = settings.WebhookSecret,
                SyncEnabled = settings.SyncEnabled,
                MaxRetryAttempts = settings.MaxRetryAttempts,
                TimeoutSeconds = settings.TimeoutSeconds,
                LastSyncedAt = lastSyncedAt,
            };

            if (_initialized && !_settings.SyncEnabled)
            {
                lock (_timerLock)
                {
                    _timer?.Dispose();
                    _timer = null;
                }

                UpdateStatus(SyncStatus.Idle, null);
            }
        }
        finally
        {
            _gate.Release();
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

                _logger.LogInformation("正在冲刷待处理的远程同步事件。");
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
            _logger.LogError(ex, "远程同步冲刷失败。");
        }
    }

    /// <summary>
    /// 创建带当前“超时秒数”设置的请求取消源；外部取消令牌存在时联动取消。
    /// </summary>
    /// <param name="externalToken">调用方已有的取消令牌，可为 <see cref="CancellationToken.None"/>。</param>
    private CancellationTokenSource CreateRequestTimeoutSource(CancellationToken externalToken = default)
    {
        var cts = externalToken == default
            ? new CancellationTokenSource()
            : CancellationTokenSource.CreateLinkedTokenSource(externalToken);

        cts.CancelAfter(TimeSpan.FromSeconds(Math.Max(1, _settings.TimeoutSeconds)));
        return cts;
    }

    private async Task InitializeCoreAsync()
    {
        if (_initialized)
            return;

        try
        {
            _settings = await _settingsRepo.LoadAsync();

            lock (_stateLock)
            {
                _snapshot.Clear();
                foreach (var item in _todoService.Items)
                    _snapshot[item.Id] = Copy(item);
            }

            _initialized = true;

            if (!_settings.SyncEnabled)
            {
                _logger.LogInformation("远程同步已禁用；跳过初始化网络调用。");
                UpdateStatus(SyncStatus.Idle, null);
                return;
            }

            _logger.LogInformation("远程同步已启用：先比对服务器更新时间，再决定推拉。");
            var meta = await FetchMetaAsync();
            if (meta is null)
                return;
            if (meta.NeedPull)
            {
                await PullTodoListAsync(meta.ServerUpdatedAt);
                return;
            }

            await PushPendingOnlyAsync();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "远程同步初始化失败。");
            UpdateStatus(SyncStatus.Error, ex.Message);
        }
    }

    private void OnServiceChanged(object? sender, EventArgs e)
    {
        // 只做差异对比并入队（快速、无 I/O）；由后台分发循环消费队列。
        if (_suppressChanged || !_initialized || !_settings.SyncEnabled)
            return;

        ActivateTimer();
    }

    private void ActivateTimer()
    {
        lock (_timerLock)
        {
            _timer?.Dispose();
            _timer = new Timer(OnTick, null, TimeSpan.FromSeconds(5), Timeout.InfiniteTimeSpan);
        }
    }

    private void OnTick(object? state)
    {
        _timer!.Dispose();
        _timer = null;

        // 设置可能在定时器等待期间被关闭；关闭后不再产生新的同步分发。
        if (!_settings.SyncEnabled)
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
                        item.HasSynced = false;
                        enqueued++;
                    }
                    else if (!string.Equals(previous.Title, item.Title, StringComparison.Ordinal))
                    {
                        EnqueueLocked(Copy(item), EventTypes.Updated);
                        item.HasSynced = false;
                        enqueued++;
                    }
                }
                else
                {
                    EnqueueLocked(Copy(item), EventTypes.Added);
                    item.HasSynced = false;
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
            _logger.LogError(ex, "todo分发失败。");
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
        if (!_settings.SyncEnabled)
            return;

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

            try
            {
                // 限制每批推送最多发送 15 条todo
                for (int i = 0; i < batch.Count; i += 15)
                {
                    await SendAsync(batch.Skip(i)
                        .Take(15)
                        .ToList());
                }

            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "推送todo到远端时发生错误");
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
    /// 发送一批待办到 /api/update，最多重试
    /// <see cref="RemoteServerSettings.MaxRetryAttempts"/> + 1 次。
    /// 成功后将现存条目标记为已同步；全部失败则保持待处理。
    /// </summary>
    private async Task SendAsync(List<PendingEvent> items)
    {
        // TODO: todo同步和webhook状态同步状态分离
        UpdateStatus(SyncStatus.Syncing, null);

        // 构建请求体 (更新待办和 Webhooks共用 )
        var updatedAt = UtcTimeOffset.NowOffset.ToString("O", CultureInfo.InvariantCulture);
        var envelopes = new List<dynamic>();
        var types = new List<string>();
        var ids = new List<Guid>();

        foreach (var item in items)
        {
            types.Add(item.Type);
            ids.Add(item.Snapshot.Id);

            envelopes.Add(new
            {
                eventType = item.Type,
                timestamp = UtcTimeOffset.NowOffset.ToString("O", CultureInfo.InvariantCulture),
                payload = new
                {
                    id = item.Snapshot.Id,
                    title = item.Snapshot.Title,
                    isCompleted = item.Snapshot.IsCompleted,
                    createdAt = item.Snapshot.CreatedAt,
                    completedAt = item.Snapshot.CompletedAt,
                },
            });
        }
        var body = new
        {
            eventType = "update",
            updatedAt = updatedAt,
            events = envelopes,
        };

        var eventId = Guid.NewGuid();
        var rawBody = JsonSerializer.Serialize(body, SnakeCaseOption);
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
        var signature = HermesWebhookSigner.ComputeSignature(_settings.WebhookSecret, timestamp, rawBody);
        var url = $"{_settings.ServerBaseUrl.TrimEnd('/')}/api/update";
        var webhookUrl = $"{_settings.HermesBaseUrl.TrimEnd('/')}/webhooks/{_settings.WebhookRouteName}";
        var messagesUrl = $"{_settings.ServerBaseUrl.TrimEnd('/')}/api/messages";

        var totalAttempts = Math.Max(0, _settings.MaxRetryAttempts) + 1;

        // 多次尝试
        for (var attempt = 1; attempt <= totalAttempts; attempt++)
        {
            try
            {
                using var requestTimeout = CreateRequestTimeoutSource();
                using var request = new HttpRequestMessage(HttpMethod.Post, url);
                request.Content = new StringContent(rawBody, Encoding.UTF8, "application/json");
                request.Headers.TryAddWithoutValidation("X-Webhook-Timestamp", timestamp);
                request.Headers.TryAddWithoutValidation("X-Webhook-Signature-V2", signature);
                request.Headers.TryAddWithoutValidation("X-Request-ID", eventId.ToString());

                using var response = await _httpClient.SendAsync(
                    request, HttpCompletionOption.ResponseHeadersRead, requestTimeout.Token);
                if (response.IsSuccessStatusCode)
                {
                    _logger.LogInformation(
                        "共 {Count} 个todo已被接收（HTTP {StatusCode}）。Types: {Types}。Ids:{Ids}",
                        items.Count,  (int)response.StatusCode, string.Join("\n;", types),  string.Join("\n;", ids));
                    await _todoService.MarkSyncedAsync(ids);
                    RefreshPendingSyncCount();

                    // 服务端已用本次 updated_at 刷新 todo-meta.json；
                    // 客户端同步推进 LastSyncedAt，避免把自己的推送误判为需要拉取。
                    _settings.LastSyncedAt = updatedAt;
                    await _settingsRepo.SaveAsync(_settings);

                    await EnqueueWebhookSnapshot(new WebhookSnapshot(
                        rawBody,
                        timestamp,
                        signature,
                        webhookUrl,
                        messagesUrl,
                        eventId.ToString()));
                    return;
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    _logger.LogWarning(
                        "共 {Count} 个todo被限流（429），退避等待（第 {Attempt}/{Total} 次尝试）。",
                        items.Count, attempt, totalAttempts);
                    if (attempt < totalAttempts)
                        await Task.Delay(TimeSpan.FromSeconds(2));
                    continue;
                }

                if (response.StatusCode == HttpStatusCode.InternalServerError)
                {
                    try
                    {
                        // 将成功部分标记 HasSynced 为 true，并推送 Hermes
                        var template = new
                        {
                            success = false,
                            ErrorIds = new List<string>(),
                            SuccessIds = new List<string>()
                        };
                        dynamic? content =
                            await response.Content.ReadFromJsonAsync(template.GetType(), SnakeCaseOption);
                        if (content is null)
                        {
                            UpdateStatus(SyncStatus.Error, $"远端返回错误");
                            _logger.LogError("Response反序列化失败，远端返回错误");
                        }
                        else
                        {
                            var errorIds = content.ErrorIds as List<string> ?? new List<string>();
                            var successIds = content.SuccessIds as List<string> ?? new List<string>();
                            var successes = new List<Guid>();
                            var successTodos = new List<dynamic>();

                            _logger.LogError("共有 {Count} 个 Todo 推送错误。Ids: {Ids}", errorIds.Count, string.Join(",\n ", errorIds));

                            foreach (var successId in successIds)
                            {
                                if (Guid.TryParse(successId, out var id))
                                {
                                    successes.Add(id);

                                    var item = envelopes.FirstOrDefault(x => (Guid)x.payload.id == id);
                                    if (item is not null)
                                    {
                                        successTodos.Add(item);
                                    }
                                }
                            }

                            await _todoService.MarkSyncedAsync(successes);
                            RefreshPendingSyncCount();

                            // 服务端会为成功的部分用本次 updated_at 刷新 todo-meta.json；
                            // 这里同步推进 LastSyncedAt，避免下次把自己的推送误判为需要拉取。
                            if (successes.Count > 0)
                            {
                                _settings.LastSyncedAt = updatedAt;
                                await _settingsRepo.SaveAsync(_settings);
                            }

                            UpdateStatus(SyncStatus.Error, $"有{errorIds.Count}个todo推送错误");

                            // 将成功推送的todo重组为新的请求体，投递到后台 Webhook 队列
                            var webhookBody = new
                            {
                                eventType = "update",
                                updatedAt = updatedAt,
                                events = successTodos,
                            };
                            var rawWebhookBody = JsonSerializer.Serialize(webhookBody, SnakeCaseOption);
                            var timestamp2 = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
                            var signature2 = HermesWebhookSigner.ComputeSignature(_settings.WebhookSecret, timestamp2, rawWebhookBody);

                            await EnqueueWebhookSnapshot(new WebhookSnapshot(
                                rawWebhookBody,
                                timestamp2,
                                signature2,
                                webhookUrl,
                                messagesUrl,
                                eventId.ToString()));
                        }
                    }
                    catch (JsonException)
                    {
                        UpdateStatus(SyncStatus.Error, $"远端返回错误");
                        _logger.LogError("Response反序列化失败，远端返回错误");
                    }
                    return;
                }

                _logger.LogWarning(
                    "共 {Count} 个todo推送失败，HTTP {StatusCode}（第 {Attempt}/{Total} 次尝试）。Types: {Types}。Ids: {Ids}",
                    items.Count, (int)response.StatusCode, attempt, totalAttempts,
                    string.Join(", ", types), string.Join(", ", ids));
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
            {
                _logger.LogWarning(
                    ex, "共 {Count} 个待办的同步推送网络错误（第 {Attempt}/{Total} 次尝试）。Types: {Types}。Ids: {Ids}",
                    items.Count, attempt, totalAttempts,
                    string.Join(", ", types), string.Join(", ", ids));
            }
        }

        _logger.LogError(
            "共 {Count} 个todo已用尽全部 {TotalAttempts} 次尝试；条目保持待处理。Types: {Types}。Ids: {Ids}",
            items.Count, totalAttempts, string.Join(", ", types), string.Join(", ", ids));
        UpdateStatus(SyncStatus.Error, $"共 {items.Count} 个待办的同步推送在 {totalAttempts} 次尝试后失败。");
        RefreshPendingSyncCount();
    }

    private async Task EnqueueWebhookSnapshot(WebhookSnapshot snapshot)
    {
        if (!_webhookReactionEnabled)
            return;

        await _channel.Writer.WriteAsync(snapshot);
        lock (_webhookWorkerLock)
        {
            if (_webhookWorker is { IsCompleted: false })
                return;

            _webhookWorker = Task.Run(() => ConsumeWebhookJobsAsync(_webhookCts.Token));
        }
    }

    private async Task ConsumeWebhookJobsAsync(CancellationToken cancellationToken)
    {
        try
        {
            await foreach (var snapshot in _channel.Reader.ReadAllAsync(cancellationToken))
            {
                try
                {
                    await ExecuteWebhookJobAsync(snapshot, cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "执行 Webhook 任务时发生错误。");
                }
            }
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Webhook 后台任务已取消。");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Webhook 后台任务意外终止。");
        }
    }

    private async Task ExecuteWebhookJobAsync(WebhookSnapshot snapshot, CancellationToken cancellationToken)
    {
        _logger.LogInformation("正在尝试 Webhook");

        try
        {
            // POST重试，共3次
            for (int j = 0; j <= 3; j++)
            {
                using var requestTimeout = CreateRequestTimeoutSource(cancellationToken);
                using var request = new HttpRequestMessage(HttpMethod.Post, snapshot.WebhookUrl);
                request.Content = new StringContent(snapshot.RawBody, Encoding.UTF8, "application/json");
                request.Headers.TryAddWithoutValidation("X-Webhook-Timestamp", snapshot.Timestamp);
                request.Headers.TryAddWithoutValidation("X-Webhook-Signature-V2", snapshot.Signature);
                request.Headers.TryAddWithoutValidation("X-Request-ID", snapshot.RequestId);

                using var response = await _httpClient.SendAsync(request, requestTimeout.Token);

                if (response.IsSuccessStatusCode)
                {
                    _logger.LogInformation("推送成功 (Webhooks)。");
                    await PollAgentMessageAsync(snapshot.MessagesUrl, cancellationToken);
                    return;
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    // 限流，等待 3 秒，最多重复3次
                    _logger.LogWarning("(Webhooks) 请求数过多，退避等待，重复次数：{Count}", j);
                    if (j == 3)
                    {
                        _logger.LogError("(Webhooks) 请求数过多");
                        UpdateStatus(SyncStatus.Error, "拉取Agent消息时出现异常");
                        return;
                    }

                    await Task.Delay(TimeSpan.FromSeconds(3), cancellationToken);
                }
                else if (response.StatusCode == HttpStatusCode.InternalServerError)
                {
                    // 服务器问题 / Hermes 问题
                    _logger.LogWarning("(Webhooks) 服务器内部出错，重复次数：{Count}", j);
                    if (j == 3)
                    {
                        _logger.LogError("(Webhooks) 服务器内部出错");
                        UpdateStatus(SyncStatus.Error, "拉取Agent消息时出现异常");
                        return;
                    }
                }
                else
                {
                    _logger.LogWarning("(Webhooks) 推送至 Hermes时出错，重复次数：{Count}", j);
                    if (j == 3)
                    {
                        _logger.LogError("(Webhooks) 推送至 Hermes时出错。Http: {StatusCode}", (int)response.StatusCode);
                        UpdateStatus(SyncStatus.Error, "拉取Agent消息时出现异常");
                        return;
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Webhook 任务已取消。");
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            _logger.LogError("(Webhooks) 推送至 Hermes时出错: {Message}", ex.Message);
            UpdateStatus(SyncStatus.Error, "拉取Agent消息时出现异常");
        }
    }

    private async Task PollAgentMessageAsync(string messagesUrl, CancellationToken cancellationToken)
    {
        var success = false;

        // 等待 Agent反应后拉取 Messages，最多重试 3 次，每次等待 30 秒
        for (int i = 0; i <= 3; i++)
        {
            await Task.Delay(_agentReactionPollInterval, cancellationToken);

            try
            {
                using var requestTimeout = CreateRequestTimeoutSource(cancellationToken);
                using var msgResponse = await _httpClient.GetAsync(new Uri(messagesUrl), requestTimeout.Token);

                if (msgResponse.StatusCode == HttpStatusCode.OK)
                {
                    var template = new
                    {
                        Exist = false,
                        Text = "",
                        Time = ""
                    };

                    dynamic? m = await msgResponse.Content.ReadFromJsonAsync(template.GetType(), SnakeCaseOption);
                    if (m is null)
                    {
                        _logger.LogWarning("远端messages-to-user.json 已损坏或不存在。已重复：{Count}", i);
                        continue;
                    }

                    if (m.Exist == true)
                    {
                        GetMessageSuccessful?.Invoke(this, new GetMessageSuccessfulEventArgs(m.Text));
                        success = true;
                    }

                    _logger.LogInformation("Webhooks重试第{Count}次，messages-to-user.json 仍未被创建", i);
                }
                else if (msgResponse.StatusCode == HttpStatusCode.InternalServerError)
                {
                    var template = new
                    {
                        Detail = ""
                    };

                    dynamic? m = await msgResponse.Content.ReadFromJsonAsync(template.GetType(), SnakeCaseOption);
                    if (m is not null)
                    {
                        _logger.LogWarning("Webhooks时服务器内部出现问题: {Detail}，重试第{Count}次。", (string?)m.Detail, i);

                    }
                }
                else
                {
                    _logger.LogWarning("Webhooks时出现问题, Http: {StatusCode}，重试第{Count}次。", (int)msgResponse.StatusCode, i);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Webhooks时发生错误。重试次数：{Count}", i);
            }
            finally
            {
                if (success)
                {
                    _logger.LogInformation("Webhook成功，Agent消息已拉取");
                    UpdateStatus(SyncStatus.Success, null);
                }
                else
                {
                    UpdateStatus(SyncStatus.Error, "拉取Agent消息时出现异常");
                }
            }

            if (success)
                break;
        }
    }

    /// <summary>
    /// 请求服务器元数据，并依据 <c>updatedAt</c> 与本地 <see cref="RemoteServerSettings.LastSyncedAt"/>
    /// 决定是否需要拉取。调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    /// <returns>
    /// 拉取决策与服务器todo.json 的更新时间；失败时置 <see cref="SyncStatus.Error"/> 并返回 null。
    /// </returns>
    private async Task<MetaResult?> FetchMetaAsync()
    {
        UpdateStatus(SyncStatus.Pulling, null);

        var baseUrl = _settings.ServerBaseUrl.TrimEnd('/');
        var metaUrl = $"{baseUrl}/api/todo/meta";

        MetaDate? meta;
        try
        {
            using var requestTimeout = CreateRequestTimeoutSource();
            using var metaResponse = await _httpClient.GetAsync(metaUrl, requestTimeout.Token);
            if (metaResponse.StatusCode != HttpStatusCode.OK)
            {
                UpdateStatus(SyncStatus.Error, $"元数据请求返回 HTTP {(int)metaResponse.StatusCode}。");
                return null;
            }

            meta = await metaResponse.Content.ReadFromJsonAsync<MetaDate>(SnakeCaseOption);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or NotSupportedException)
        {
            _logger.LogError(ex, "todo-meta请求失败。");
            UpdateStatus(SyncStatus.Error, $"请求失败：{ex.Message}");
            return null;
        }

        if (meta?.UpdatedAt is not { Length: > 0 } updatedAt
            || !DateTimeOffset.TryParse(updatedAt, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal, out var parsed))
        {
            UpdateStatus(SyncStatus.Error, "元数据响应未包含有效的 updated_at。");
            return null;
        }

        var serverUtc = parsed.ToLocalTime();

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
    /// <see cref="RemoteServerSettings.LastSyncedAt"/> 为服务器更新时间。
    /// 调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    private async Task PullTodoListAsync(DateTimeOffset serverUpdatedAt)
    {
        var baseUrl = _settings.ServerBaseUrl.TrimEnd('/');
        var listUrl = $"{baseUrl}/api/todo";

        List<TodoItem>? pulled;
        try
        {
            using var requestTimeout = CreateRequestTimeoutSource();
            using var listResponse = await _httpClient.GetAsync(listUrl, requestTimeout.Token);
            if (listResponse.StatusCode != HttpStatusCode.OK)
            {
                UpdateStatus(SyncStatus.Error, $"todo请求返回 HTTP {(int)listResponse.StatusCode}。");
                return;
            }

            pulled = await listResponse.Content.ReadFromJsonAsync<List<TodoItem>>(SnakeCaseOption);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or NotSupportedException)
        {
            _logger.LogError(ex, "todo请求失败。");
            UpdateStatus(SyncStatus.Error, $"todo请求失败：{ex.Message}");
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

        _settings.LastSyncedAt = serverUpdatedAt.ToOffset(UtcTimeOffset.Offset).ToString("O", CultureInfo.InvariantCulture);
        await _settingsRepo.SaveAsync(_settings);

        _logger.LogInformation("已从服务器拉取 {Count} 条todo；上次同步时间更新为 {UpdatedAt}。",
            pulled.Count, _settings.LastSyncedAt);
        UpdateStatus(SyncStatus.Success, null);
        RefreshPendingSyncCount();
    }

    /// <summary>
    /// 服务器todo.json 更新时间不晚于上次同步时：仅推送本地待处理项。
    /// 调用方必须持有 <see cref="_gate"/>。
    /// </summary>
    private async Task PushPendingOnlyAsync()
    {
        _logger.LogInformation("服务器 todo.json 更新时间不晚于上次同步；推送本地todo。");
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

    public void Dispose()
    {
        _webhookCts.Cancel();
        _channel.Writer.TryComplete();
        _webhookCts.Dispose();
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

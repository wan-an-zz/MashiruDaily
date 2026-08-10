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
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// Hermes AI-sync worker. Watches <see cref="ITodoService"/> for changes and pushes
/// them as signed webhook events to Hermes, and implements the startup push-then-pull
/// flow from the communication protocol. Keeps a value snapshot of the last observed
/// items so it can diff changes without touching <c>TodoService</c>'s own lock.
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

    private sealed class MetaDate
    {
        public string? Date { get; set; }
    }

    private static readonly JsonSerializerOptions CamelCaseJson = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
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
    private SyncStatus status;

    [ObservableProperty]
    private string? lastError;

    [ObservableProperty]
    private int pendingSyncCount;

    /// <inheritdoc />
    public event EventHandler? StatusChanged;

    /// <summary>
    /// Creates the sync service. Subscribes to <see cref="ITodoService.Changed"/> so
    /// future mutations are diffed and pushed automatically.
    /// </summary>
    /// <param name="todoService">Single source of truth for todos. Must be initialized first.</param>
    /// <param name="settingsRepo">Persisted Hermes settings store.</param>
    /// <param name="logger">Structured logger.</param>
    /// <param name="httpClient">Optional client (used for tests); a default one is created when omitted.</param>
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

                _logger.LogInformation("Manual sync requested; pushing pending items then pulling.");
                EnqueuePendingAsUpdated();
                await DispatchCoreAsync();
                await PullFromServerAsync();
            }
            finally
            {
                _gate.Release();
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Hermes SyncNowAsync failed.");
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

                _logger.LogInformation("Flushing pending Hermes events.");
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
            _logger.LogError(ex, "Hermes FlushAsync failed.");
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
                _logger.LogInformation("Hermes sync is disabled; skipping initialization network calls.");
                UpdateStatus(SyncStatus.Idle, null);
                return;
            }

            _logger.LogInformation("Hermes sync enabled; pushing pending items then pulling.");
            EnqueuePendingAsUpdated();
            await DispatchCoreAsync();
            await PullFromServerAsync();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Hermes sync initialization failed.");
            UpdateStatus(SyncStatus.Error, ex.Message);
        }
    }

    private void OnServiceChanged(object? sender, EventArgs e)
    {
        // Diff + enqueue only (fast, no I/O); the fire-and-forget dispatch drains the queue.
        if (_suppressChanged || !_initialized || !_settings.SyncEnabled)
            return;

        if (DiffAndEnqueue() > 0)
        {
            RefreshPendingSyncCount();
            _ = DispatchPendingAsync();
        }
    }

    /// <summary>
    /// Compares the live items against the snapshot and enqueues one event per change.
    /// </summary>
    /// <returns>The number of events enqueued.</returns>
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
    /// Enqueues every live item with <c>HasSynced == false</c> as a
    /// <c>todo_updated</c> upsert (used by startup, manual sync and shutdown flush).
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
    /// Fire-and-forget entry point: guarantees a single drain loop is running and
    /// re-triggers itself if events arrive between the drain and the guard reset.
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
            _logger.LogError(ex, "Hermes pending dispatch failed.");
        }
        finally
        {
            Interlocked.Exchange(ref _dispatchRunning, 0);
        }

        if (HasPending())
            _ = DispatchPendingAsync();
    }

    /// <summary>
    /// Drains the pending queue, sending one event at a time (sequential, rate-limit safe).
    /// Caller must hold <see cref="_gate"/>.
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
                    _logger.LogError(ex, "Unexpected error sending {EventType} for todo {Id}.",
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
    /// Sends one signed webhook event with retries up to
    /// <see cref="HermesSettings.MaxRetryAttempts"/> + 1 attempts.
    /// On success the live item is marked synced; on exhaustion it stays pending.
    /// </summary>
    private async Task SendAsync(TodoItem item, string eventType)
    {
        var eventId = Guid.NewGuid();
        var envelope = new
        {
            type = eventType,
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
        var rawBody = JsonSerializer.Serialize(envelope, CamelCaseJson);
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
                        "Webhook {EventType} for todo {Id} accepted (HTTP {StatusCode}).",
                        eventType, item.Id, (int)response.StatusCode);
                    await _todoService.MarkSyncedAsync(new[] { item.Id });
                    RefreshPendingSyncCount();
                    UpdateStatus(SyncStatus.Success, null);
                    return;
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests)
                {
                    _logger.LogWarning(
                        "Webhook rate-limited (429) for todo {Id}, backing off (attempt {Attempt}/{Total}).",
                        item.Id, attempt, totalAttempts);
                    if (attempt < totalAttempts)
                        await Task.Delay(TimeSpan.FromSeconds(2));
                    continue;
                }

                _logger.LogWarning(
                    "Webhook {EventType} for todo {Id} failed with HTTP {StatusCode} (attempt {Attempt}/{Total}).",
                    eventType, item.Id, (int)response.StatusCode, attempt, totalAttempts);
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
            {
                _logger.LogWarning(
                    ex, "Webhook {EventType} for todo {Id} network error (attempt {Attempt}/{Total}).",
                    eventType, item.Id, attempt, totalAttempts);
            }
        }

        _logger.LogError(
            "Webhook {EventType} for todo {Id} exhausted all {TotalAttempts} attempts; item stays pending.",
            eventType, item.Id, totalAttempts);
        UpdateStatus(SyncStatus.Error, $"Webhook {eventType} for {item.Id} failed after {totalAttempts} attempts.");
        RefreshPendingSyncCount();
    }

    /// <summary>
    /// Startup pull flow: GET meta, compare date, skip on local pending, then
    /// GET the whole list and replace the local collection.
    /// </summary>
    private async Task PullFromServerAsync()
    {
        UpdateStatus(SyncStatus.Pulling, null);

        var baseUrl = _settings.ServerBaseUrl.TrimEnd('/');
        var metaUrl = $"{baseUrl}/api/todo/meta";
        var listUrl = $"{baseUrl}/api/todo";

        MetaDate? meta;
        try
        {
            using var metaResponse = await _httpClient.GetAsync(metaUrl);
            if (metaResponse.StatusCode != HttpStatusCode.OK)
            {
                UpdateStatus(SyncStatus.Error, $"Meta request returned HTTP {(int)metaResponse.StatusCode}.");
                return;
            }

            meta = await metaResponse.Content.ReadFromJsonAsync<MetaDate>(CamelCaseJson);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or NotSupportedException)
        {
            _logger.LogError(ex, "Hermes meta request failed.");
            UpdateStatus(SyncStatus.Error, $"Meta request failed: {ex.Message}");
            return;
        }

        if (meta?.Date is null)
        {
            UpdateStatus(SyncStatus.Error, "Meta response did not include a date.");
            return;
        }

        if (string.Equals(meta.Date, _settings.LastSyncedDate, StringComparison.Ordinal))
        {
            _logger.LogInformation("Server date {Date} matches last synced date; skipping pull.", meta.Date);
            UpdateStatus(SyncStatus.Success, null);
            return;
        }

        if (_todoService.Items.Any(x => !x.HasSynced))
        {
            _logger.LogWarning("Local pending edits exist; skipping pull.");
            UpdateStatus(SyncStatus.Skipped, "有本地未同步修改，跳过拉取");
            return;
        }

        List<TodoItem>? pulled;
        try
        {
            using var listResponse = await _httpClient.GetAsync(listUrl);
            if (listResponse.StatusCode != HttpStatusCode.OK)
            {
                UpdateStatus(SyncStatus.Error, $"Todo list request returned HTTP {(int)listResponse.StatusCode}.");
                return;
            }

            pulled = await listResponse.Content.ReadFromJsonAsync<List<TodoItem>>();
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException or NotSupportedException)
        {
            _logger.LogError(ex, "Hermes todo list request failed.");
            UpdateStatus(SyncStatus.Error, $"Todo list request failed: {ex.Message}");
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

        _settings.LastSyncedDate = meta.Date;
        await _settingsRepo.SaveAsync(_settings);

        _logger.LogInformation("Pulled {Count} todos from server; last synced date is {Date}.",
            pulled.Count, meta.Date);
        UpdateStatus(SyncStatus.Success, null);
        RefreshPendingSyncCount();
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

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// Default <see cref="ITodoService"/> implementation. All mutations go through
/// the service so behaviour stays consistent and can be unit tested without a UI.
/// Mutations mutate in-memory state synchronously, raise <see cref="Changed"/>, then
/// trigger a single-flight flush loop that persists a coalesced latest-wins snapshot.
/// </summary>
public sealed class TodoService : ITodoService
{
    private readonly ITodoRepository _repository;
    private readonly ILogger<TodoService> _logger;
    private readonly List<TodoItem> _items = new();
    private readonly object _gate = new();
    private IReadOnlyList<TodoItem>? _pendingSnapshot;
    private bool _flushRunning;
    private Task _flushTask = Task.CompletedTask;

    public TodoService(ITodoRepository repository, ILogger<TodoService> logger)
    {
        _repository = repository;
        _logger = logger;
    }

    public event EventHandler? Changed;

    public IReadOnlyList<TodoItem> Items => _items;

    public async Task InitializeAsync()
    {
        var loaded = await _repository.LoadAsync();
        _items.AddRange(loaded);
        _logger.LogInformation("Loaded {Count} todos.", _items.Count);
    }

    public async Task FlushAsync()
    {
        Task flushTask;
        lock (_gate)
        {
            _pendingSnapshot = SnapshotItems();
            if (_flushRunning)
            {
                flushTask = _flushTask;
            }
            else
            {
                _flushRunning = true;
                flushTask = RunFlushLoopAsync();
                _flushTask = flushTask;
            }
        }

        await flushTask;
    }

    public Task AddAsync(string title)
    {
        var trimmed = (title ?? string.Empty).Trim();
        if (trimmed.Length == 0)
            return Task.CompletedTask;

        var item = new TodoItem { Title = trimmed };
        _items.Add(item);
        _logger.LogInformation("Todo added: '{Title}' ({Id}).", trimmed, item.Id);
        OnChanged();
        RequestFlush();
        return Task.CompletedTask;
    }

    public Task RemoveAsync(TodoItem item)
    {
        if (_items.Remove(item))
        {
            _logger.LogInformation("Todo removed: '{Title}' ({Id}).", item.Title, item.Id);
            OnChanged();
            RequestFlush();
        }

        return Task.CompletedTask;
    }

    public Task ToggleAsync(TodoItem item)
    {
        item.IsCompleted = !item.IsCompleted;
        item.CompletedAt = item.IsCompleted ? DateTime.Now : null;
        _logger.LogInformation("Todo {State}: '{Title}' ({Id}).",
            item.IsCompleted ? "completed" : "reopened", item.Title, item.Id);
        OnChanged();
        RequestFlush();
        return Task.CompletedTask;
    }

    public Task UpdateTitleAsync(TodoItem item, string title)
    {
        var trimmed = (title ?? string.Empty).Trim();
        if (trimmed.Length == 0 || string.Equals(item.Title, trimmed, StringComparison.Ordinal))
            return Task.CompletedTask;

        var previous = item.Title;
        item.Title = trimmed;
        _logger.LogInformation("Todo renamed: '{Previous}' -> '{New}' ({Id}).", previous, trimmed, item.Id);
        OnChanged();
        RequestFlush();
        return Task.CompletedTask;
    }

    public Task ReplaceAllAsync(IReadOnlyList<TodoItem> items)
    {
        lock (_gate)
        {
            _items.Clear();
            _items.AddRange(items);
        }

        _logger.LogInformation("Replaced all todos with {Count} items.", items.Count);
        OnChanged();
        RequestFlush();
        return Task.CompletedTask;
    }

    public Task MarkSyncedAsync(IReadOnlyCollection<Guid> ids)
    {
        int matched = 0;
        lock (_gate)
        {
            var idSet = new HashSet<Guid>(ids);
            foreach (var item in _items)
            {
                if (idSet.Contains(item.Id))
                {
                    item.HasSynced = true;
                    matched++;
                }
            }
        }

        _logger.LogInformation("Marked {Matched} of {Requested} todos as synced.", matched, ids.Count);
        RequestFlush();
        return Task.CompletedTask;
    }

    private void OnChanged() => Changed?.Invoke(this, EventArgs.Empty);

    private void RequestFlush()
    {
        lock (_gate)
        {
            _pendingSnapshot = SnapshotItems();
            if (_flushRunning)
                return;
            _flushRunning = true;
            _flushTask = RunFlushLoopAsync();
        }
    }

    private IReadOnlyList<TodoItem> SnapshotItems()
    {
        var snapshot = new List<TodoItem>(_items.Count);
        foreach (var item in _items)
        {
            snapshot.Add(new TodoItem
            {
                Id = item.Id,
                Title = item.Title,
                IsCompleted = item.IsCompleted,
                HasSynced = item.HasSynced,
                CreatedAt = item.CreatedAt,
                CompletedAt = item.CompletedAt,
            });
        }
        return snapshot;
    }

    private async Task RunFlushLoopAsync()
    {
        while (true)
        {
            IReadOnlyList<TodoItem>? snapshot;
            lock (_gate)
            {
                snapshot = _pendingSnapshot;
                if (snapshot is null)
                {
                    _flushRunning = false;
                    return;
                }
                _pendingSnapshot = null;
            }

            try
            {
                await _repository.SaveAsync(snapshot);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to flush todos to storage.");
            }
        }
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// <see cref="ITodoService"/> 的默认实现。所有变更都经由本服务，
/// 以保证行为一致且无需 UI 即可进行单元测试。
/// 变更会同步修改内存状态、触发 <see cref="Changed"/>，
/// 然后启动一个单飞冲刷循环，将合并后的「最后写者胜」快照持久化。
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

    public IReadOnlyList<TodoItem> Items => _items;

    public event EventHandler? Changed;

    public TodoService(ITodoRepository repository, ILogger<TodoService> logger)
    {
        _repository = repository;
        _logger = logger;
    }

    public async Task InitializeAsync()
    {
        var loaded = await _repository.LoadAsync();
        _items.AddRange(loaded);
        _logger.LogInformation("已加载 {Count} 条待办。", _items.Count);
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
        _logger.LogInformation("已添加待办：'{Title}' ({Id})。", trimmed, item.Id);
        OnChanged();
        RequestFlush();
        return Task.CompletedTask;
    }

    public Task RemoveAsync(TodoItem item)
    {
        if (_items.Remove(item))
        {
            _logger.LogInformation("已删除待办：'{Title}' ({Id})。", item.Title, item.Id);
            OnChanged();
            RequestFlush();
        }

        return Task.CompletedTask;
    }

    public Task ToggleAsync(TodoItem item)
    {
        item.IsCompleted = !item.IsCompleted;
        item.CompletedAt = item.IsCompleted ? DateTime.Now : null;
        _logger.LogInformation("待办{State}：'{Title}' ({Id})。",
            item.IsCompleted ? "已完成" : "重新打开", item.Title, item.Id);
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
        _logger.LogInformation("待办已重命名：'{Previous}' -> '{New}' ({Id})。", previous, trimmed, item.Id);
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

        _logger.LogInformation("已用 {Count} 条数据整体替换全部待办。", items.Count);
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

        _logger.LogInformation("已将 {Requested} 条待办中的 {Matched} 条标记为已同步。", ids.Count, matched);
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
                _logger.LogError(ex, "待办冲刷到存储失败。");
            }
        }
    }
}

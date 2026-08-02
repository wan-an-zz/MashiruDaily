using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using MashiruDaily.Abstracts;
using MashiruDaily.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Services;

/// <summary>
/// Default <see cref="ITodoService"/> implementation. All mutations go through
/// the service so behaviour stays consistent and can be unit tested without a UI.
/// </summary>
public sealed class TodoService : ITodoService
{
    private readonly ITodoRepository _repository;
    private readonly ILogger<TodoService> _logger;
    private readonly List<TodoItem> _items;

    public TodoService(ITodoRepository repository, ILogger<TodoService> logger)
    {
        _repository = repository;
        _logger = logger;
        _items = _repository.LoadAsync().GetAwaiter().GetResult().ToList();
    }

    public event EventHandler? Changed;

    public IReadOnlyList<TodoItem> Items => _items;

    public Task AddAsync(string title)
    {
        var trimmed = (title ?? string.Empty).Trim();
        if (trimmed.Length == 0)
            return Task.CompletedTask;

        var item = new TodoItem { Title = trimmed };
        _items.Add(item);
        _logger.LogInformation("Todo added: '{Title}' ({Id}).", trimmed, item.Id);
        OnChanged();
        return Task.CompletedTask;
    }

    public Task RemoveAsync(TodoItem item)
    {
        if (_items.Remove(item))
        {
            _logger.LogInformation("Todo removed: '{Title}' ({Id}).", item.Title, item.Id);
            OnChanged();
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
        return Task.CompletedTask;
    }

    private void OnChanged() => Changed?.Invoke(this, EventArgs.Empty);
}

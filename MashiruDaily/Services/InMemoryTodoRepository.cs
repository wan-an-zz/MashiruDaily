using System.Collections.Generic;
using System.Threading.Tasks;
using MashiruDaily.Abstracts;
using MashiruDaily.Models;

namespace MashiruDaily.Services;

/// <summary>
/// In-memory repository. Keeps data for the lifetime of the process; replace
/// with a durable implementation (SQLite / JSON file) when persistence is needed.
/// </summary>
public sealed class InMemoryTodoRepository : ITodoRepository
{
    private readonly List<TodoItem> _items = new();

    public Task<IReadOnlyList<TodoItem>> LoadAsync()
        => Task.FromResult<IReadOnlyList<TodoItem>>(_items);

    public Task SaveAsync(IReadOnlyList<TodoItem> items)
    {
        _items.Clear();
        _items.AddRange(items);
        return Task.CompletedTask;
    }
}

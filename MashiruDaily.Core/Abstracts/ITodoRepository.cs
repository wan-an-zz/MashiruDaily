using System.Collections.Generic;
using System.Threading.Tasks;
using MashiruDaily.Models;

namespace MashiruDaily.Abstracts;

/// <summary>
/// Persistence abstraction for todo items. Swap the implementation for a
/// database / file based store without touching the rest of the app.
/// </summary>
public interface ITodoRepository
{
    Task<IReadOnlyList<TodoItem>> LoadAsync();

    Task SaveAsync(IReadOnlyList<TodoItem> items);
}

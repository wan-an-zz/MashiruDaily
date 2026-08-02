using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using MashiruDaily.Models;

namespace MashiruDaily.Abstracts;

/// <summary>
/// Application-level business logic for todos. It is the single source of truth
/// for the todo collection and raises <see cref="Changed"/> whenever data changes,
/// letting any consumer (e.g. a view-model) react and re-render.
/// </summary>
public interface ITodoService
{
    event EventHandler? Changed;

    /// <summary>All todos, pending and completed.</summary>
    IReadOnlyList<TodoItem> Items { get; }

    Task AddAsync(string title);

    Task RemoveAsync(TodoItem item);

    Task ToggleAsync(TodoItem item);

    Task UpdateTitleAsync(TodoItem item, string title);
}

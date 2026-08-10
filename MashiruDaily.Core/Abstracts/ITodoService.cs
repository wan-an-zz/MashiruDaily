using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

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

    /// <summary>Loads persisted todos. Must be awaited once before the UI is shown.</summary>
    Task InitializeAsync();

    /// <summary>Waits for all pending changes to be persisted. Call at shutdown.</summary>
    Task FlushAsync();

    Task AddAsync(string title);

    Task RemoveAsync(TodoItem item);

    Task ToggleAsync(TodoItem item);

    Task UpdateTitleAsync(TodoItem item, string title);

    /// <summary>
    /// Replaces the entire in-memory collection with <paramref name="items"/>,
    /// keeping the same item references. Raises <see cref="Changed"/> and persists.
    /// </summary>
    Task ReplaceAllAsync(IReadOnlyList<TodoItem> items);

    /// <summary>
    /// Marks the live items whose ids are in <paramref name="ids"/> as synced and
    /// persists without raising <see cref="Changed"/> so sync watchers do not echo back.
    /// </summary>
    Task MarkSyncedAsync(IReadOnlyCollection<Guid> ids);
}

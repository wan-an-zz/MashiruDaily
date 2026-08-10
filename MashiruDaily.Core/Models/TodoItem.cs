using System;

namespace MashiruDaily.Models;

/// <summary>
/// A single todo entry. Plain data model; state is managed by <see cref="MashiruDaily.Abstracts.ITodoService"/>.
/// </summary>
public sealed class TodoItem
{
    public Guid Id { get; init; } = Guid.NewGuid();

    public string Title { get; set; } = string.Empty;

    public bool IsCompleted { get; set; }

    /// <summary>
    /// True once this item has been pushed to the external sync store.
    /// Defaults to false; existing JSON files deserialize to false (backward compatible).
    /// </summary>
    public bool HasSynced { get; set; }

    public DateTime CreatedAt { get; init; } = DateTime.Now;

    public DateTime? CompletedAt { get; set; }
}

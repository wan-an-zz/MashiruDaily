using System;
using System.Threading.Tasks;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// Aggregated state of the Hermes AI-sync worker, surfaced to the UI.
/// </summary>
public enum SyncStatus
{
    /// <summary>No sync activity in progress and no result to report yet.</summary>
    Idle,

    /// <summary>Pushing pending changes to Hermes via webhook.</summary>
    Syncing,

    /// <summary>Pulling the todo list from the server.</summary>
    Pulling,

    /// <summary>The last sync operation completed successfully.</summary>
    Success,

    /// <summary>The last sync operation failed; see <see cref="IHermesSyncService.LastError"/>.</summary>
    Error,

    /// <summary>The pull was intentionally skipped (e.g. local pending edits exist).</summary>
    Skipped,
}

/// <summary>
/// Orchestrates Hermes AI-sync: watches the todo service for changes and pushes them
/// as signed webhook events, plus the startup push-then-pull flow defined in the
/// communication protocol.
/// </summary>
public interface IHermesSyncService
{
    /// <summary>Current sync status; changed via <see cref="StatusChanged"/>.</summary>
    SyncStatus Status { get; }

    /// <summary>Human-readable description of the last failure, if any.</summary>
    string? LastError { get; }

    /// <summary>Number of local todos that still need to be pushed to Hermes.</summary>
    int PendingSyncCount { get; }

    /// <summary>
    /// Raised whenever <see cref="Status"/>, <see cref="LastError"/> or
    /// <see cref="PendingSyncCount"/> change.
    /// </summary>
    event EventHandler? StatusChanged;

    /// <summary>
    /// Loads settings, pushes pending items and runs the startup pull.
    /// Safe to call once; later calls are no-ops.
    /// </summary>
    Task InitializeAsync();

    /// <summary>Manual sync: re-pushes pending items, then runs the pull flow.</summary>
    Task SyncNowAsync();

    /// <summary>Best-effort push of pending items; never throws. Call at shutdown.</summary>
    Task FlushAsync();
}

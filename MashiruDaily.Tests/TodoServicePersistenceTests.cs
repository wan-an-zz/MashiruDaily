using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using MashiruDaily.Abstracts;
using MashiruDaily.Models;
using MashiruDaily.Services;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace MashiruDaily.Tests;

public sealed class BlockingTodoRepository : ITodoRepository
{
    private readonly IReadOnlyList<TodoItem> _seed;
    private readonly object _lock = new();
    private readonly List<IReadOnlyList<TodoItem>> _saved = new();
    private readonly TaskCompletionSource _firstSaveStarted =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource _releaseFirstSave =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int _saveCount;
    private int _activeSaves;
    private int _maxActiveSaves;

    public BlockingTodoRepository(params TodoItem[] seed) => _seed = seed;

    public Task<IReadOnlyList<TodoItem>> LoadAsync() => Task.FromResult(_seed);

    public Task FirstSaveStarted => _firstSaveStarted.Task;

    public void ReleaseFirstSave() => _releaseFirstSave.TrySetResult();

    public int MaxActiveSaves
    {
        get { lock (_lock) return _maxActiveSaves; }
    }

    public IReadOnlyList<TodoItem>? LastSaved
    {
        get { lock (_lock) return _saved.Count == 0 ? null : _saved[^1]; }
    }

    public List<IReadOnlyList<TodoItem>> Saved => _saved;

    public async Task SaveAsync(IReadOnlyList<TodoItem> items)
    {
        bool first;
        lock (_lock)
        {
            first = _saveCount == 0;
            _saveCount++;
            _activeSaves++;
            _maxActiveSaves = Math.Max(_maxActiveSaves, _activeSaves);
            _saved.Add(items.ToList());
        }

        if (first)
            _firstSaveStarted.TrySetResult();

        try
        {
            if (first)
                await _releaseFirstSave.Task;
        }
        finally
        {
            lock (_lock) _activeSaves--;
        }
    }
}

public class TodoServicePersistenceTests
{
    private static async Task WaitForSaveAsync(
        BlockingTodoRepository repo, Func<IReadOnlyList<TodoItem>?, bool> predicate, int timeoutMs = 2000)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (true)
        {
            if (predicate(repo.LastSaved))
                return;
            if (DateTime.UtcNow >= deadline)
                throw new TimeoutException("Timed out waiting for expected save state.");
            await Task.Delay(10);
        }
    }

    [Fact]
    public async Task InitializeAsync_LoadsSeedFromRepository()
    {
        var repo = new BlockingTodoRepository(new TodoItem { Title = "seed" });
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);

        await service.InitializeAsync();

        Assert.Single(service.Items);
        Assert.Equal("seed", service.Items[0].Title);
    }

    [Fact]
    public async Task Mutations_PersistFinalState()
    {
        var repo = new BlockingTodoRepository();
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.AddAsync("A");
        await service.AddAsync("B");
        await service.AddAsync("C");
        await repo.FirstSaveStarted;
        repo.ReleaseFirstSave();
        await WaitForSaveAsync(repo, s => s is not null && s.Count == 3);

        var last = repo.LastSaved!;
        Assert.Equal(3, last.Count);
        Assert.Equal(new[] { "A", "B", "C" }, last.Select(x => x.Title).OrderBy(t => t).ToArray());
    }

    [Fact]
    public async Task RapidMutations_CoalesceIntoSingleFlush()
    {
        var repo = new BlockingTodoRepository();
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.AddAsync("A");
        await repo.FirstSaveStarted;
        await service.AddAsync("B");
        await service.AddAsync("C");
        repo.ReleaseFirstSave();
        await WaitForSaveAsync(repo, s => s is not null && s.Count == 3);

        Assert.Equal(1, repo.MaxActiveSaves);
        var last = repo.LastSaved!;
        Assert.Equal(new[] { "A", "B", "C" }, last.Select(x => x.Title).OrderBy(t => t).ToArray());
    }

    [Fact]
    public async Task Toggle_And_Rename_ArePersisted()
    {
        var item = new TodoItem { Title = "X" };
        var repo = new BlockingTodoRepository(item);
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.ToggleAsync(item);
        await service.UpdateTitleAsync(item, "Y");
        await repo.FirstSaveStarted;
        repo.ReleaseFirstSave();
        await WaitForSaveAsync(repo, s => s is not null && s[0].Title == "Y" && s[0].IsCompleted);

        var last = repo.LastSaved!;
        Assert.True(last.Single().IsCompleted);
        Assert.Equal("Y", last.Single().Title);
        Assert.NotNull(last.Single().CompletedAt);
    }

    [Fact]
    public async Task Snapshot_IsAValueCopy_NotAffectedByLaterMutation()
    {
        var repo = new BlockingTodoRepository();
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.AddAsync("X");
        await repo.FirstSaveStarted;

        await service.ToggleAsync(service.Items[0]);
        repo.ReleaseFirstSave();
        await WaitForSaveAsync(repo, s => s is not null && s[0].IsCompleted);

        var first = repo.Saved[0];
        Assert.Single(first);
        Assert.False(first[0].IsCompleted);
        Assert.Null(first[0].CompletedAt);

        var last = repo.LastSaved!;
        Assert.True(last[0].IsCompleted);
        Assert.NotNull(last[0].CompletedAt);
    }

    [Fact]
    public async Task FlushAsync_WaitsForPendingWrites()
    {
        var repo = new BlockingTodoRepository();
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.AddAsync("A");
        await repo.FirstSaveStarted;

        var flushTask = service.FlushAsync();
        Assert.False(flushTask.IsCompleted);

        repo.ReleaseFirstSave();
        await flushTask;

        var last = repo.LastSaved!;
        Assert.Single(last);
        Assert.Equal("A", last[0].Title);
    }
}

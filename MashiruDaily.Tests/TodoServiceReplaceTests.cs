using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using MashiruDaily.Core.Models;
using MashiruDaily.Core.Services;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace MashiruDaily.Tests;

public class TodoServiceReplaceTests : IDisposable
{
    private readonly string _dir;

    public TodoServiceReplaceTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "MashiruDaily.Tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
            Directory.Delete(_dir, recursive: true);
    }

    private static async Task WaitForSaveAsync(
        BlockingTodoRepositoryService repo, Func<IReadOnlyList<TodoItem>?, bool> predicate, int timeoutMs = 2000)
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
    public async Task ReplaceAllAsync_SwapsItems_RaisesChanged_AndPersistsFinalList()
    {
        var repo = new BlockingTodoRepositoryService(new TodoItem { Title = "old" });
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        var changedCount = 0;
        service.Changed += (_, _) => changedCount++;

        var replacement = new[] { new TodoItem { Title = "A" }, new TodoItem { Title = "B" } };
        await service.ReplaceAllAsync(replacement);

        Assert.Equal(2, service.Items.Count);
        Assert.Same(replacement[0], service.Items[0]);
        Assert.Same(replacement[1], service.Items[1]);
        Assert.Equal(1, changedCount);

        await repo.FirstSaveStarted;
        repo.ReleaseFirstSave();
        await WaitForSaveAsync(repo, s => s is not null && s.Count == 2);

        var last = repo.LastSaved!;
        Assert.Equal(new[] { "A", "B" }, last.Select(x => x.Title).OrderBy(t => t).ToArray());
    }

    [Fact]
    public async Task MarkSyncedAsync_FlipsHasSyncedOnMatchingIdsOnly_AndPersistsThroughRepoRoundTrip()
    {
        var repo = new TodoRepoService(NullLogger<TodoRepoService>.Instance, _dir);
        var items = new[]
        {
            new TodoItem { Title = "A" },
            new TodoItem { Title = "B" },
            new TodoItem { Title = "C" },
        };
        await repo.SaveAsync(items);

        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.MarkSyncedAsync(new[] { items[0].Id, items[1].Id });
        await service.FlushAsync();

        Assert.True(service.Items[0].HasSynced);
        Assert.True(service.Items[1].HasSynced);
        Assert.False(service.Items[2].HasSynced);

        var reloaded = await repo.LoadAsync();
        Assert.True(reloaded.Single(x => x.Id == items[0].Id).HasSynced);
        Assert.True(reloaded.Single(x => x.Id == items[1].Id).HasSynced);
        Assert.False(reloaded.Single(x => x.Id == items[2].Id).HasSynced);
    }

    [Fact]
    public async Task MarkSyncedAsync_DoesNotRaiseChanged()
    {
        var repo = new TodoRepoService(NullLogger<TodoRepoService>.Instance, _dir);
        var item = new TodoItem { Title = "A" };
        await repo.SaveAsync(new[] { item });

        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        var changedCount = 0;
        service.Changed += (_, _) => changedCount++;

        await service.MarkSyncedAsync(new[] { item.Id });
        await service.FlushAsync();

        Assert.Equal(0, changedCount);
    }

    [Fact]
    public async Task SnapshotItems_RoundTripsHasSynced()
    {
        var repo = new TodoRepoService(NullLogger<TodoRepoService>.Instance, _dir);
        var item = new TodoItem { Title = "A" };
        await repo.SaveAsync(new[] { item });

        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        service.Items[0].HasSynced = true;
        await service.FlushAsync();

        var reloaded = await repo.LoadAsync();
        var synced = Assert.Single(reloaded);
        Assert.True(synced.HasSynced);
    }
}

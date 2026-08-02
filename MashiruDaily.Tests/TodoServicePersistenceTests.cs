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

public sealed class RecordingTodoRepository : ITodoRepository
{
    private readonly IReadOnlyList<TodoItem> _seed;

    public RecordingTodoRepository(params TodoItem[] seed) => _seed = seed;

    public List<IReadOnlyList<TodoItem>> Saved { get; } = new();

    public Task<IReadOnlyList<TodoItem>> LoadAsync() => Task.FromResult(_seed);

    public async Task SaveAsync(IReadOnlyList<TodoItem> items)
    {
        await Task.Delay(50);
        lock (Saved)
            Saved.Add(items.ToList());
    }
}

public class TodoServicePersistenceTests
{
    private static async Task WaitForFlushAsync(int ms = 400)
        => await Task.Delay(ms);

    [Fact]
    public async Task InitializeAsync_LoadsSeedFromRepository()
    {
        var repo = new RecordingTodoRepository(new TodoItem { Title = "seed" });
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);

        await service.InitializeAsync();

        Assert.Single(service.Items);
        Assert.Equal("seed", service.Items[0].Title);
    }

    [Fact]
    public async Task Mutations_PersistFinalState()
    {
        var repo = new RecordingTodoRepository();
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.AddAsync("A");
        await service.AddAsync("B");
        await service.AddAsync("C");
        await WaitForFlushAsync();

        Assert.NotEmpty(repo.Saved);
        var last = repo.Saved[^1];
        Assert.Equal(3, last.Count);
        Assert.Equal(new[] { "A", "B", "C" }, last.Select(x => x.Title).OrderBy(t => t).ToArray());
    }

    [Fact]
    public async Task RapidMutations_CoalesceIntoSingleFlush()
    {
        var repo = new RecordingTodoRepository();
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.AddAsync("A");
        await service.AddAsync("B");
        await service.AddAsync("C");
        await WaitForFlushAsync();

        Assert.True(repo.Saved.Count < 3, $"Expected fewer than 3 saves, got {repo.Saved.Count}");
    }

    [Fact]
    public async Task Toggle_And_Rename_ArePersisted()
    {
        var item = new TodoItem { Title = "X" };
        var repo = new RecordingTodoRepository(item);
        var service = new TodoService(repo, NullLogger<TodoService>.Instance);
        await service.InitializeAsync();

        await service.ToggleAsync(item);
        await service.UpdateTitleAsync(item, "Y");
        await WaitForFlushAsync();

        var last = repo.Saved[^1];
        Assert.True(last.Single().IsCompleted);
        Assert.Equal("Y", last.Single().Title);
        Assert.NotNull(last.Single().CompletedAt);
    }
}

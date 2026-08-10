using System;
using System.IO;
using System.Threading.Tasks;
using MashiruDaily.Core.Models;
using MashiruDaily.Core.Services;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace MashiruDaily.Tests;

public class JsonTodoRepositoryTests : IDisposable
{
    private readonly string _dir;

    private readonly string _file;

    private readonly JsonTodoRepository _repository;

    public JsonTodoRepositoryTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "MashiruDaily.Tests", Guid.NewGuid().ToString("N"));
        _file = Path.Combine(_dir, "todos.json");
        _repository = new JsonTodoRepository(NullLogger<JsonTodoRepository>.Instance, _dir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
            Directory.Delete(_dir, recursive: true);
    }

    [Fact]
    public async Task RoundTrip_PreservesAllFields()
    {
        var items = new[]
        {
            new TodoItem { Title = "写代码" },
            new TodoItem { Title = "买菜", IsCompleted = true, CompletedAt = DateTime.Now, HasSynced = true },
        };

        await _repository.SaveAsync(items);
        var loaded = await _repository.LoadAsync();

        Assert.Equal(2, loaded.Count);
        Assert.Equal(items[0].Id, loaded[0].Id);
        Assert.Equal(items[0].Title, loaded[0].Title);
        Assert.False(loaded[0].IsCompleted);
        Assert.False(loaded[0].HasSynced);
        Assert.Equal(items[1].Title, loaded[1].Title);
        Assert.True(loaded[1].IsCompleted);
        Assert.NotNull(loaded[1].CompletedAt);
        Assert.True(loaded[1].HasSynced);
        Assert.Equal(items[1].CreatedAt, loaded[1].CreatedAt);
    }

    [Fact]
    public async Task LoadAsync_WhenFileMissing_ReturnsEmpty()
    {
        var loaded = await _repository.LoadAsync();

        Assert.Empty(loaded);
    }

    [Fact]
    public async Task LoadAsync_WhenFileCorrupt_ReturnsEmptyAndDoesNotThrow()
    {
        Directory.CreateDirectory(_dir);
        await File.WriteAllTextAsync(_file, "{ not valid json !!!");

        var loaded = await _repository.LoadAsync();

        Assert.Empty(loaded);
    }

    [Fact]
    public async Task SaveAsync_CreatesDirectoryAndWritesAtomicFile()
    {
        await _repository.SaveAsync(new[] { new TodoItem { Title = "A" } });

        Assert.True(File.Exists(_file));
        Assert.False(File.Exists(_file + ".tmp"));
    }
}

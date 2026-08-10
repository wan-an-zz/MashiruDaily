using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// Persists todos as a single JSON array under <c>%APPDATA%\MashiruDaily\todos.json</c>.
/// Writes are atomic (tmp file + move) so a crash never leaves a half-written file.
/// Missing or corrupt files load as an empty list; IO failures are logged, never thrown.
/// </summary>
public sealed class JsonTodoRepository : ITodoRepository
{
    private readonly ILogger<JsonTodoRepository> _logger;
    private readonly string _directory;
    private readonly string _filePath;

    public JsonTodoRepository(ILogger<JsonTodoRepository> logger, string? dataDirectory = null)
    {
        _logger = logger;
        _directory = dataDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "MashiruDaily");
        _filePath = Path.Combine(_directory, "todos.json");
    }

    public Task<IReadOnlyList<TodoItem>> LoadAsync()
    {
        try
        {
            if (!File.Exists(_filePath))
                return Task.FromResult<IReadOnlyList<TodoItem>>(Array.Empty<TodoItem>());

            var json = File.ReadAllText(_filePath);
            var items = JsonSerializer.Deserialize<List<TodoItem>>(json);
            return Task.FromResult<IReadOnlyList<TodoItem>>(items ?? new List<TodoItem>());
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to load todos from '{File}'; starting empty.", _filePath);
            return Task.FromResult<IReadOnlyList<TodoItem>>(new List<TodoItem>());
        }
    }

    public async Task SaveAsync(IReadOnlyList<TodoItem> items)
    {
        try
        {
            Directory.CreateDirectory(_directory);
            var json = JsonSerializer.Serialize(items, new JsonSerializerOptions { WriteIndented = true });
            var tmp = _filePath + ".tmp";
            await File.WriteAllTextAsync(tmp, json);
            File.Move(tmp, _filePath, overwrite: true);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to save todos to '{File}'.", _filePath);
        }
    }
}

using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Converters;
using MashiruDaily.Core.Models;
using Microsoft.Extensions.Logging;

namespace MashiruDaily.Core.Services;

/// <summary>
/// 将待办以单个 JSON 数组持久化到 <c>%APPDATA%\MashiruDaily\todos.json</c>。
/// 写入是原子的（tmp 文件 + move），崩溃不会留下半写的文件。
/// 缺失或损坏的文件按空列表加载；IO 失败只记录日志，绝不抛出。
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
            _logger.LogError(ex, "从 '{File}' 加载待办失败；以空列表开始。", _filePath);
            return Task.FromResult<IReadOnlyList<TodoItem>>(new List<TodoItem>());
        }
    }

    public async Task SaveAsync(IReadOnlyList<TodoItem> items)
    {
        try
        {
            Directory.CreateDirectory(_directory);
            var options = new JsonSerializerOptions
            {
                WriteIndented = true,
                Converters = { new LocalDateTimeJsonConverter() },
            };
            var json = JsonSerializer.Serialize(items, options);
            var tmp = _filePath + ".tmp";
            await File.WriteAllTextAsync(tmp, json);
            File.Move(tmp, _filePath, overwrite: true);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "保存待办到 '{File}' 失败。", _filePath);
        }
    }
}

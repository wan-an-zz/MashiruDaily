using System;
using MashiruDaily.Core.Services;

namespace MashiruDaily.Core.Models;

/// <summary>
/// 单条待办条目。纯数据模型；状态由 <see cref="MashiruDaily.Core.Abstracts.ITodoService"/> 管理。
/// </summary>
public sealed class TodoItem
{
    public Guid Id { get; init; } = Guid.NewGuid();

    public string Title { get; set; } = string.Empty;

    public bool IsCompleted { get; set; }

    /// <summary>
    /// 该条目是否已推送到外部同步存储。
    /// 默认为 false；已有的 JSON 文件反序列化后也是 false（向后兼容）。
    /// </summary>
    public bool HasSynced { get; set; }

    public DateTime CreatedAt { get; init; } = UtcTimeOffset.Now;

    public DateTime? CompletedAt { get; set; }
}

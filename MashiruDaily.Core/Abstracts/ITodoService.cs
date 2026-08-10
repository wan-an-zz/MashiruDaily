using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// 待办事项的应用层业务逻辑，是待办集合的唯一数据源；
/// 数据一旦变化就触发 <see cref="Changed"/>，让任意消费者（如视图模型）做出响应并重新渲染。
/// </summary>
public interface ITodoService
{
    event EventHandler? Changed;

    /// <summary>全部待办，包括待完成与已完成。</summary>
    IReadOnlyList<TodoItem> Items { get; }

    /// <summary>加载已持久化的待办。UI 展示前必须等待一次。</summary>
    Task InitializeAsync();

    /// <summary>等待所有待持久化的变更落盘。关闭时调用。</summary>
    Task FlushAsync();

    Task AddAsync(string title);

    Task RemoveAsync(TodoItem item);

    Task ToggleAsync(TodoItem item);

    Task UpdateTitleAsync(TodoItem item, string title);

    /// <summary>
    /// 用 <paramref name="items"/> 整体替换内存中的集合，保持元素引用不变。
    /// 会触发 <see cref="Changed"/> 并持久化。
    /// </summary>
    Task ReplaceAllAsync(IReadOnlyList<TodoItem> items);

    /// <summary>
    /// 将 id 在 <paramref name="ids"/> 中的现存元素标记为已同步并持久化，
    /// 但不会触发 <see cref="Changed"/>，避免同步观察者回环。
    /// </summary>
    Task MarkSyncedAsync(IReadOnlyCollection<Guid> ids);
}

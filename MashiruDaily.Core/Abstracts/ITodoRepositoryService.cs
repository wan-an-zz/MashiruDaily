using System.Collections.Generic;
using System.Threading.Tasks;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// 待办事项的持久化抽象。如需换成数据库或文件存储，只需替换实现，
/// 无需改动应用其余部分。
/// </summary>
public interface ITodoRepositoryService
{
    Task<IReadOnlyList<TodoItem>> LoadAsync();

    Task SaveAsync(IReadOnlyList<TodoItem> items);
}

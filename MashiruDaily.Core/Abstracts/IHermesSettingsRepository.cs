using System.Threading.Tasks;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// Hermes AI 同步设置的持久化抽象。如需换成其他存储，只需替换实现，
/// 无需改动应用其余部分。
/// </summary>
public interface IHermesSettingsRepository
{
    Task<HermesSettings> LoadAsync();

    Task SaveAsync(HermesSettings settings);
}

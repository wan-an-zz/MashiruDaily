using System.Threading.Tasks;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// 远程服务器同步设置的持久化抽象。
/// </summary>
public interface IRemoteServerSettingsRepository
{
    Task<RemoteServerSettings> LoadAsync();

    Task SaveAsync(RemoteServerSettings settings);
}

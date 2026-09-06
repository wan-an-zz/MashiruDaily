using System;
using System.Threading.Tasks;
using MashiruDaily.Core.Events;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// 远程同步服务的聚合状态，供 UI 展示。
/// </summary>
public enum SyncStatus
{
    /// <summary>当前没有同步活动。</summary>
    Idle,

    /// <summary>正在向服务器推送待处理变更。</summary>
    Syncing,

    /// <summary>正在从服务器拉取待办列表。</summary>
    Pulling,

    /// <summary>最近一次同步成功。</summary>
    Success,

    /// <summary>最近一次同步失败；详见 <see cref="IRemoteSyncService.LastError"/>。</summary>
    Error,

    /// <summary>拉取被有意跳过。</summary>
    Skipped,
}

/// <summary>
/// 编排远程同步：监听待办变更，向服务器 /api/update 推送事件，
/// 并执行“先比对 meta，再决定拉取或推送”的启动逻辑。
/// </summary>
public interface IRemoteSyncService
{
    /// <summary>当前同步状态；变化通过 <see cref="StatusChanged"/> 通知。</summary>
    SyncStatus Status { get; }

    /// <summary>最近一次失败的可读描述；没有失败则为 null。</summary>
    string? LastError { get; }

    /// <summary>仍待推送到服务器的本地待办数量。</summary>
    int PendingSyncCount { get; }

    /// <summary>
    /// 状态、错误或待推送数量变化时触发。
    /// </summary>
    event EventHandler? StatusChanged;

    /// <summary>
    /// 当成功拉取到 Messages-to-user.json时触发
    /// </summary>
    event EventHandler<GetMessageSuccessfulEventArgs>? GetMessageSuccessful;

    /// <summary>
    /// 加载设置并执行启动同步。只应调用一次。
    /// </summary>
    Task InitializeAsync();

    /// <summary>
    /// 手动同步：按当前 meta 决定拉取或推送。
    /// </summary>
    Task SyncNowAsync();

    /// <summary>
    /// 将用户可编辑的远程同步设置立即应用到运行中的同步服务（无需重启）。
    /// 仅更新连接地址、密钥、开关、重试与超时等字段；内部 <see cref="RemoteServerSettings.LastSyncedAt"/>
    /// 由同步服务维护，不会被本方法重置。
    /// </summary>
    Task ApplySettingsAsync(RemoteServerSettings settings);

    /// <summary>尽力推送待处理项，绝不抛异常。关闭时调用。</summary>
    Task FlushAsync();
}

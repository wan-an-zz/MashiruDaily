using System;
using System.Threading.Tasks;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// Hermes AI 同步后台任务的聚合状态，供 UI 展示。
/// </summary>
public enum SyncStatus
{
    /// <summary>当前没有同步活动，也没有需要上报的结果。</summary>
    Idle,

    /// <summary>正在通过 Webhook 向 Hermes 推送待处理的变更。</summary>
    Syncing,

    /// <summary>正在从服务器拉取待办列表。</summary>
    Pulling,

    /// <summary>最近一次同步操作成功完成。</summary>
    Success,

    /// <summary>最近一次同步操作失败；详见 <see cref="IRemoteSyncService.LastError"/>。</summary>
    Error,

    /// <summary>拉取被有意跳过（例如存在本地待同步的修改）。</summary>
    Skipped,
}

/// <summary>
/// 编排 Hermes AI 同步：监听待办服务的变更并作为已签名的 Webhook 事件推送，
/// 同时实现通信协议中定义的启动「先推后拉」流程。
/// </summary>
public interface IRemoteSyncService
{
    /// <summary>当前同步状态；变化通过 <see cref="StatusChanged"/> 通知。</summary>
    SyncStatus Status { get; }

    /// <summary>最近一次失败的可读描述；没有失败则为 null。</summary>
    string? LastError { get; }

    /// <summary>仍需推送到 Hermes 的本地待办数量。</summary>
    int PendingSyncCount { get; }

    /// <summary>
    /// 每当 <see cref="Status"/>、<see cref="LastError"/> 或
    /// <see cref="PendingSyncCount"/> 变化时触发。
    /// </summary>
    event EventHandler? StatusChanged;

    /// <summary>
    /// 加载设置、推送待处理项并执行启动拉取。
    /// 只应调用一次；之后的调用是空操作。
    /// </summary>
    Task InitializeAsync();

    /// <summary>手动同步：重新推送待处理项，然后执行拉取流程。</summary>
    Task SyncNowAsync();

    /// <summary>尽力推送待处理项，绝不抛异常。关闭时调用。</summary>
    Task FlushAsync();
}

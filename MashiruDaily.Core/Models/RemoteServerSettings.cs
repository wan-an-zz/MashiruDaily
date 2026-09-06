namespace MashiruDaily.Core.Models;

/// <summary>
/// 远程服务器同步设置。纯数据模型；<see cref="CreateDefault"/> 提供无设置文件时的默认值。
/// </summary>
public sealed class RemoteServerSettings
{
    /// <summary>
    /// 拉取与推送共用的服务器基础地址，例如 "http://192.168.1.100:8123"。
    /// </summary>
    public string ServerBaseUrl { get; set; } = string.Empty;

    /// <summary>
    /// Hermes 地址；用于推送更新快照触发 Agent 反应，也用于设置页“连接测试”。
    /// </summary>
    public string HermesBaseUrl { get; set; } = "http://localhost:8644";

    /// <summary>
    /// Hermes Webhook 路由名，用于推送更新快照触发 Agent 反应。
    /// </summary>
    public string WebhookRouteName { get; set; } = "todo-sync";

    /// <summary>
    /// 用于给 /api/update 与 Hermes Webhook 请求计算 HMAC-SHA256 签名的密钥。
    /// </summary>
    public string WebhookSecret { get; set; } = string.Empty;

    /// <summary>
    /// 是否启用远程同步。
    /// </summary>
    public bool SyncEnabled { get; set; }

    /// <summary>
    /// 推送失败时的最大重试次数。
    /// </summary>
    public int MaxRetryAttempts { get; set; } = 3;

    /// <summary>
    /// HTTP 请求超时秒数。
    /// </summary>
    public double TimeoutSeconds { get; set; } = 10;

    /// <summary>
    /// 上一次修改待办或同步待办的时间
    /// </summary>
    public string? LastSyncedAt { get; set; }

    /// <summary>
    /// 无设置文件时使用的默认值。
    /// </summary>
    public static RemoteServerSettings CreateDefault() => new()
    {
        ServerBaseUrl = string.Empty,
        HermesBaseUrl = "http://localhost:8644",
        WebhookRouteName = "todo-sync",
        WebhookSecret = string.Empty,
        SyncEnabled = false,
        MaxRetryAttempts = 3,
        TimeoutSeconds = 10,
        LastSyncedAt = null,
    };
}

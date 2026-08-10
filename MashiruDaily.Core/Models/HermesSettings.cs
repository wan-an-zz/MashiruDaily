namespace MashiruDaily.Core.Models;

/// <summary>
/// Hermes AI 同步功能的持久化设置。纯数据模型；
/// <see cref="CreateDefault"/> 提供尚无设置文件时使用的默认值。
/// </summary>
public sealed class HermesSettings
{
    /// <summary>
    /// 拉取用的服务器基础地址，例如 "http://192.168.1.100:8080"。
    /// </summary>
    public string ServerBaseUrl { get; set; } = string.Empty;

    /// <summary>
    /// Hermes 守护进程基础地址。
    /// </summary>
    public string HermesBaseUrl { get; set; } = "http://localhost:8644";

    /// <summary>
    /// Hermes Webhook 的路由名。
    /// </summary>
    public string WebhookRouteName { get; set; } = "todo-sync";

    /// <summary>
    /// 用于签署 Hermes Webhook V2 请求的 HMAC 密钥。
    /// </summary>
    public string WebhookSecret { get; set; } = string.Empty;

    /// <summary>
    /// 是否启用 Hermes AI 同步功能。
    /// </summary>
    public bool SyncEnabled { get; set; }

    /// <summary>
    /// 同步操作失败时的最大重试次数。
    /// </summary>
    public int MaxRetryAttempts { get; set; } = 3;

    /// <summary>
    /// 同步操作的超时秒数。
    /// </summary>
    public double TimeoutSeconds { get; set; } = 10;

    /// <summary>
    /// 客户端记录的服务器待办日期，为不透明的 "yyyy-MM-dd" 字符串。
    /// </summary>
    public string? LastSyncedDate { get; set; }

    /// <summary>
    /// 尚无设置文件时使用的工厂默认值。
    /// </summary>
    public static HermesSettings CreateDefault() => new()
    {
        ServerBaseUrl = string.Empty,
        HermesBaseUrl = "http://localhost:8644",
        WebhookRouteName = "todo-sync",
        WebhookSecret = string.Empty,
        SyncEnabled = false,
        MaxRetryAttempts = 3,
        TimeoutSeconds = 10,
        LastSyncedDate = null,
    };
}

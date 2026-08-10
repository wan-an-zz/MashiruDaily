namespace MashiruDaily.Models;

/// <summary>
/// Persisted settings for the Hermes AI-sync feature. Plain data model;
/// <see cref="CreateDefault"/> supplies the factory defaults used when no
/// settings file exists yet.
/// </summary>
public sealed class HermesSettings
{
    /// <summary>
    /// GET-pull server base, e.g. "http://192.168.1.100:8080".
    /// </summary>
    public string ServerBaseUrl { get; set; } = string.Empty;

    /// <summary>
    /// Hermes daemon base URL.
    /// </summary>
    public string HermesBaseUrl { get; set; } = "http://localhost:8644";

    /// <summary>
    /// Route name for the Hermes webhook.
    /// </summary>
    public string WebhookRouteName { get; set; } = "todo-sync";

    /// <summary>
    /// HMAC secret used to sign Hermes webhook V2 requests.
    /// </summary>
    public string WebhookSecret { get; set; } = string.Empty;

    /// <summary>
    /// Whether the Hermes AI-sync feature is enabled.
    /// </summary>
    public bool SyncEnabled { get; set; }

    /// <summary>
    /// Maximum retry attempts for failed sync operations.
    /// </summary>
    public int MaxRetryAttempts { get; set; } = 3;

    /// <summary>
    /// Timeout in seconds for sync operations.
    /// </summary>
    public double TimeoutSeconds { get; set; } = 10;

    /// <summary>
    /// Client's record of the server todo date it has, as an opaque "yyyy-MM-dd" string.
    /// </summary>
    public string? LastSyncedDate { get; set; }

    /// <summary>
    /// Factory defaults used when no settings file exists yet.
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

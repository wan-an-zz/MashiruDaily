using System;
using System.Security.Cryptography;
using System.Text;

namespace MashiruDaily.Core.Services;

/// <summary>
/// 为 Hermes Webhooks 推送请求计算签名（请求头 <c>X-Webhook-Signature-V2</c>）：
/// 对 <c>"{timestamp}.{rawBody}"</c> 的 UTF-8 字节计算小写十六进制 HMAC-SHA256。
/// </summary>
public static class HermesWebhookSigner
{
    /// <summary>
    /// 根据密钥、时间戳和原始请求体计算小写十六进制 HMAC-SHA256 签名。
    /// </summary>
    /// <param name="secret">同步设置中的共享密钥。</param>
    /// <param name="timestamp">以 <c>X-Webhook-Timestamp</c> 发送的 Unix 秒数字符串。</param>
    /// <param name="rawBody">请求体的 UTF-8 文本（与发送字节完全一致）。</param>
    /// <returns>64 位小写十六进制字符串。</returns>
    public static string ComputeSignature(string secret, string timestamp, string rawBody)
    {
        ArgumentNullException.ThrowIfNull(secret);
        ArgumentNullException.ThrowIfNull(timestamp);
        ArgumentNullException.ThrowIfNull(rawBody);

        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes($"{timestamp}.{rawBody}"));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}

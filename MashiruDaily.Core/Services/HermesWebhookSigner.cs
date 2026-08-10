using System;
using System.Security.Cryptography;
using System.Text;

namespace MashiruDaily.Core.Services;

/// <summary>
/// Signs Hermes webhook requests (protocol header <c>X-Webhook-Signature-V2</c>):
/// lowercase hex HMAC-SHA256 over the UTF-8 bytes of <c>"{timestamp}.{rawBody}"</c>.
/// </summary>
public static class HermesWebhookSigner
{
    /// <summary>
    /// Computes the lowercase hex HMAC-SHA256 signature for the given
    /// <paramref name="secret"/>, <paramref name="timestamp"/> and
    /// <paramref name="rawBody"/>.
    /// </summary>
    /// <param name="secret">Shared HMAC secret from the Hermes settings.</param>
    /// <param name="timestamp">Unix-seconds string sent as <c>X-Webhook-Timestamp</c>.</param>
    /// <param name="rawBody">The exact request body bytes as UTF-8 text.</param>
    /// <returns>A 64-character lowercase hexadecimal string.</returns>
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

using System;
using System.Security.Cryptography;
using System.Text;
using MashiruDaily.Core.Services;
using Xunit;

namespace MashiruDaily.Tests;

public class HermesWebhookSignerTests
{
    [Fact]
    public void ComputeSignature_KnownVector_MatchesIndependentHmac()
    {
        const string secret = "secret";
        const string timestamp = "1700000000";
        const string body = "{\"a\":1}";

        var actual = HermesWebhookSigner.ComputeSignature(secret, timestamp, body);

        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var expectedHash = hmac.ComputeHash(Encoding.UTF8.GetBytes($"{timestamp}.{body}"));
        var expected = Convert.ToHexString(expectedHash).ToLowerInvariant();

        Assert.Equal(expected, actual);
        Assert.Matches("^[0-9a-f]{64}$", actual);
    }

    [Fact]
    public void ComputeSignature_IsDeterministic()
    {
        const string secret = "s3cret-hmac-key";
        const string timestamp = "1754764800";
        const string body = "{\"type\":\"todo_added\",\"payload\":{\"id\":\"11111111-1111-1111-1111-111111111111\"}}";

        var first = HermesWebhookSigner.ComputeSignature(secret, timestamp, body);
        var second = HermesWebhookSigner.ComputeSignature(secret, timestamp, body);

        Assert.Equal(first, second);
        Assert.Equal(64, first.Length);
    }

    [Fact]
    public void ComputeSignature_DifferentBody_ChangesSignature()
    {
        const string secret = "secret";
        const string timestamp = "1700000000";

        var sigA = HermesWebhookSigner.ComputeSignature(secret, timestamp, "{\"a\":1}");
        var sigB = HermesWebhookSigner.ComputeSignature(secret, timestamp, "{\"a\":2}");

        Assert.NotEqual(sigA, sigB);
    }
}

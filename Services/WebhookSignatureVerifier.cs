using System.Security.Cryptography;
using System.Text;

namespace LineBotWebhook.Services;

public class WebhookSignatureVerifier : IWebhookSignatureVerifier
{
    private readonly string _channelSecret;

    public WebhookSignatureVerifier(string channelSecret)
    {
        _channelSecret = channelSecret;
    }

    public bool Verify(string body, string signature)
    {
        if (string.IsNullOrEmpty(signature))
            return false;

        var key = Encoding.UTF8.GetBytes(_channelSecret);
        var data = Encoding.UTF8.GetBytes(body);

        using var hmac = new HMACSHA256(key);
        var hash = hmac.ComputeHash(data);
        var computed = Convert.ToBase64String(hash);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(computed),
            Encoding.UTF8.GetBytes(signature));
    }
}

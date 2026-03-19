using System.Security.Cryptography;
using System.Text;

namespace LineBotWebhook.Services;

internal static class ObservabilityKeyFingerprint
{
    public static string From(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "empty";

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(value));
        return Convert.ToHexString(hash)[..12];
    }
}

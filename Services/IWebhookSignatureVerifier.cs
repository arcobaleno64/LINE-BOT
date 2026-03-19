namespace LineBotWebhook.Services;

public interface IWebhookSignatureVerifier
{
    bool Verify(string body, string signature);
}

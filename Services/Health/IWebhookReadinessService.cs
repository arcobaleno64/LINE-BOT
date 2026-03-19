namespace LineBotWebhook.Services;

public interface IWebhookReadinessService
{
    void MarkStarted();
    WebhookReadinessSnapshot GetSnapshot();
}

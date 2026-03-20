using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public sealed record WebhookQueueItem(LineEvent Event, string PublicBaseUrl)
{
    public string? EventId => string.IsNullOrWhiteSpace(Event.WebhookEventId) ? null : Event.WebhookEventId;
    public string SourceType => Event.Source?.Type ?? "unknown";
    public string MessageType => Event.Message?.Type ?? "none";
}

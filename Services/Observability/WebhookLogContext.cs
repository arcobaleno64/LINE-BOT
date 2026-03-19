using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public sealed record WebhookLogContext(
    string? EventId,
    string? HandlerType,
    string? MessageType,
    string? SourceType,
    string? UserKeyFingerprint)
{
    public static WebhookLogContext FromEvent(LineEvent evt, string? handlerType = null, string? userKey = null)
    {
        return new WebhookLogContext(
            string.IsNullOrWhiteSpace(evt.WebhookEventId) ? null : evt.WebhookEventId,
            handlerType,
            evt.Message?.Type,
            evt.Source?.Type ?? "unknown",
            userKey is null ? null : ObservabilityKeyFingerprint.From(userKey));
    }
}

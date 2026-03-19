using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public interface ILineWebhookDispatcher
{
    Task DispatchAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct);
}
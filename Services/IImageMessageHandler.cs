using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public interface IImageMessageHandler
{
    Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct);
}

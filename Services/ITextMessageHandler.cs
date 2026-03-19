using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public interface ITextMessageHandler
{
    Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct);
}

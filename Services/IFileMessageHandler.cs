using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public interface IFileMessageHandler
{
    Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct);
}

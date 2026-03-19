using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("api/line")]
public class LineWebhookController(
    IWebhookSignatureVerifier signatureVerifier,
    IPublicBaseUrlResolver publicBaseUrlResolver,
    ILineWebhookDispatcher dispatcher,
    ILogger<LineWebhookController> logger) : ControllerBase
{
    private readonly IWebhookSignatureVerifier _signatureVerifier = signatureVerifier;
    private readonly IPublicBaseUrlResolver _publicBaseUrlResolver = publicBaseUrlResolver;
    private readonly ILineWebhookDispatcher _dispatcher = dispatcher;
    private readonly ILogger<LineWebhookController> _logger = logger;

    /// <summary>LINE Messaging API Webhook Endpoint</summary>
    [HttpPost("webhook")]
    public async Task<IActionResult> Webhook(CancellationToken ct)
    {
        using var reader = new StreamReader(Request.Body, Encoding.UTF8);
        var body = await reader.ReadToEndAsync(ct);

        if (!_signatureVerifier.Verify(body, Request.Headers["x-line-signature"].ToString()))
        {
            _logger.LogWarning("Invalid LINE signature");
            return Unauthorized();
        }

        var webhook = JsonSerializer.Deserialize<LineWebhookBody>(body);
        if (webhook?.Events is null || webhook.Events.Count == 0)
            return Ok();

        var publicBaseUrl = _publicBaseUrlResolver.Resolve(Request);

        _ = Task.Run(async () =>
        {
            foreach (var evt in webhook.Events)
            {
                try
                {
                    await _dispatcher.DispatchAsync(evt, publicBaseUrl, CancellationToken.None);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error handling event {EventId}", evt.WebhookEventId);
                }
            }
        }, CancellationToken.None);

        return Ok();
    }
}

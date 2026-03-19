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
    IWebhookMetrics metrics,
    ILogger<LineWebhookController> logger) : ControllerBase
{
    private readonly IWebhookSignatureVerifier _signatureVerifier = signatureVerifier;
    private readonly IPublicBaseUrlResolver _publicBaseUrlResolver = publicBaseUrlResolver;
    private readonly ILineWebhookDispatcher _dispatcher = dispatcher;
    private readonly IWebhookMetrics _metrics = metrics;
    private readonly ILogger<LineWebhookController> _logger = logger;

    /// <summary>LINE Messaging API Webhook Endpoint</summary>
    [HttpPost("webhook")]
    public async Task<IActionResult> Webhook(CancellationToken ct)
    {
        using var reader = new StreamReader(Request.Body, Encoding.UTF8);
        var body = await reader.ReadToEndAsync(ct);
        _metrics.RecordWebhookRequest();

        if (!_signatureVerifier.Verify(body, Request.Headers["x-line-signature"].ToString()))
        {
            _metrics.RecordInvalidSignature();
            _logger.LogWarning("Invalid LINE signature");
            return Unauthorized();
        }

        var webhook = JsonSerializer.Deserialize<LineWebhookBody>(body);
        if (webhook?.Events is null || webhook.Events.Count == 0)
        {
            _logger.LogInformation("Received LINE webhook with no events");
            return Ok();
        }

        _metrics.RecordWebhookEvents(webhook.Events.Count);
        _logger.LogInformation(
            "Received LINE webhook with {EventCount} events. FirstEventId={FirstEventId}",
            webhook.Events.Count,
            webhook.Events[0].WebhookEventId);

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
                    _logger.LogError(
                        ex,
                        "Error handling event {EventId} from {SourceType} with message type {MessageType}",
                        evt.WebhookEventId,
                        evt.Source?.Type ?? "unknown",
                        evt.Message?.Type ?? "none");
                }
            }
        }, CancellationToken.None);

        return Ok();
    }
}

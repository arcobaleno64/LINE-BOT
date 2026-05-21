using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("api/line")]
[EnableRateLimiting("webhook-ip")]
public class LineWebhookController(
    IWebhookSignatureVerifier signatureVerifier,
    IPublicBaseUrlResolver publicBaseUrlResolver,
    IWebhookBackgroundQueue backgroundQueue,
    IWebhookMetrics metrics,
    IWebhookEventDeduplicationService deduplication,
    ILogger<LineWebhookController> logger) : ControllerBase
{
    private readonly IWebhookSignatureVerifier _signatureVerifier = signatureVerifier;
    private readonly IPublicBaseUrlResolver _publicBaseUrlResolver = publicBaseUrlResolver;
    private readonly IWebhookBackgroundQueue _backgroundQueue = backgroundQueue;
    private readonly IWebhookMetrics _metrics = metrics;
    private readonly IWebhookEventDeduplicationService _deduplication = deduplication;
    private readonly ILogger<LineWebhookController> _logger = logger;

    // LINE webhook payloads are small (typically < 50 KB). 256 KB caps malicious
    // pre-signature allocation; legitimate traffic is comfortably under.
    private const long MaxWebhookBodyBytes = 256 * 1024;

    /// <summary>LINE Messaging API Webhook Endpoint</summary>
    [HttpPost("webhook")]
    public async Task<IActionResult> Webhook(CancellationToken ct)
    {
        _metrics.RecordWebhookRequest();

        if (Request.ContentLength is { } declared && declared > MaxWebhookBodyBytes)
        {
            _logger.LogWarning(
                "Rejected webhook with oversize Content-Length before signature check. DeclaredBytes={DeclaredBytes}",
                declared);
            return StatusCode(StatusCodes.Status413PayloadTooLarge);
        }

        using var reader = new StreamReader(Request.Body, Encoding.UTF8);
        var buffer = new char[4096];
        var sb = new StringBuilder();
        var byteEstimate = 0L;
        int read;
        while ((read = await reader.ReadAsync(buffer.AsMemory(), ct)) > 0)
        {
            sb.Append(buffer, 0, read);
            // UTF-8 worst case ~3 bytes/char for CJK; chars*4 is a safe upper bound.
            byteEstimate = sb.Length * 4L;
            if (byteEstimate > MaxWebhookBodyBytes)
            {
                _logger.LogWarning(
                    "Rejected webhook body that exceeded body cap during read. CapBytes={CapBytes}",
                    MaxWebhookBodyBytes);
                return StatusCode(StatusCodes.Status413PayloadTooLarge);
            }
        }
        var body = sb.ToString();
        var bodyLength = Encoding.UTF8.GetByteCount(body);
        if (bodyLength > MaxWebhookBodyBytes)
        {
            _logger.LogWarning(
                "Rejected webhook body that exceeded body cap after read. BodyBytes={BodyBytes}",
                bodyLength);
            return StatusCode(StatusCodes.Status413PayloadTooLarge);
        }

        var signatureHeader = Request.Headers["x-line-signature"].ToString();
        if (!_signatureVerifier.Verify(body, signatureHeader))
        {
            _metrics.RecordInvalidSignature();
            _logger.LogWarning(
                "Invalid LINE signature. HasSignatureHeader={HasSignatureHeader} BodyLength={BodyLength}",
                !string.IsNullOrWhiteSpace(signatureHeader),
                bodyLength);
            return Unauthorized();
        }

        var webhook = JsonSerializer.Deserialize<LineWebhookBody>(body);
        if (webhook?.Events is null || webhook.Events.Count == 0)
        {
            _logger.LogInformation("Received LINE webhook with no events");
            return Ok();
        }

        _metrics.RecordWebhookEvents(webhook.Events.Count);
        var firstEventId = webhook.Events[0].WebhookEventId;
        if (!string.IsNullOrWhiteSpace(firstEventId))
        {
            _logger.LogInformation(
                "Received LINE webhook with {EventCount} events. FirstEventId={FirstEventId}",
                webhook.Events.Count,
                firstEventId);
        }
        else
        {
            _logger.LogInformation("Received LINE webhook with {EventCount} events", webhook.Events.Count);
        }

        var publicBaseUrl = _publicBaseUrlResolver.Resolve(Request);
        var enqueueSuccessCount = 0;
        var enqueueDroppedCount = 0;
        var deduplicatedCount = 0;
        foreach (var evt in webhook.Events)
        {
            // 先以 dedup 原子標記阻擋並行重複，避免「兩封同 eventId 同時入列、各自抓同一 replyToken」之競態。
            if (!_deduplication.TryMarkSeen(evt.WebhookEventId))
            {
                deduplicatedCount++;
                continue;
            }

            if (_backgroundQueue.TryEnqueue(new WebhookQueueItem(evt, publicBaseUrl)))
            {
                enqueueSuccessCount++;
            }
            else
            {
                // 入列失敗（queue 滿）即撤銷 dedup 標記，讓 LINE 之重送可再次嘗試入列。
                _deduplication.Forget(evt.WebhookEventId);
                enqueueDroppedCount++;
            }
        }

        if (deduplicatedCount > 0)
        {
            _logger.LogInformation(
                "Deduplicated duplicate webhook events. Count={Count} FirstEventId={FirstEventId}",
                deduplicatedCount,
                firstEventId);
        }

        if (enqueueDroppedCount > 0)
        {
            _logger.LogWarning(
                "Webhook enqueue dropped events. EventCount={EventCount} EnqueuedCount={EnqueuedCount} DroppedCount={DroppedCount} FirstEventId={FirstEventId}",
                webhook.Events.Count,
                enqueueSuccessCount,
                enqueueDroppedCount,
                firstEventId);
        }

        return Ok();
    }
}

using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("api/push")]
[EnableRateLimiting("push-api")]
public class PushController : ControllerBase
{
    private const int MaxBodyBytes = 4096;

    private readonly LinePushService _push;
    private readonly IConfiguration _config;
    private readonly ILogger<PushController> _logger;

    public PushController(LinePushService push, IConfiguration config, ILogger<PushController> logger)
    {
        _push = push;
        _config = config;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> Push(CancellationToken ct)
    {
        if (!ValidateHmac(out var bodyString, out var problem))
            return problem!;

        PushRequest? req;
        try
        {
            req = JsonSerializer.Deserialize<PushRequest>(bodyString, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        }
        catch
        {
            return Problem("Invalid JSON body.", statusCode: 400);
        }

        if (req is null || string.IsNullOrWhiteSpace(req.TargetId) || string.IsNullOrWhiteSpace(req.Text))
            return Problem("Missing targetId or text.", statusCode: 400);

        if (!LinePushService.IsValidGroupId(req.TargetId))
            return Problem("Invalid targetId format. Expected C[0-9a-f]{32}.", statusCode: 400);

        if (req.Text.Length > 5000)
            return Problem("Text exceeds 5000 character limit.", statusCode: 400);

        var quotaLevel = _push.GetQuotaLevel();
        if (quotaLevel == QuotaLevel.Disabled)
            return Problem("Monthly push quota exhausted.", statusCode: 503);

        var result = await _push.PushTextAsync(req.TargetId, req.Text, ct);

        _logger.LogInformation("Push API called. TargetFingerprint={TargetFingerprint} Result={Result} QuotaLevel={QuotaLevel}",
            req.TargetId.Length > 8 ? req.TargetId[..4] + "…" + req.TargetId[^4..] : "****",
            result,
            quotaLevel);

        return result switch
        {
            PushResult.Accepted or PushResult.Conflict => Ok(new { status = "accepted", quotaLevel = quotaLevel.ToString() }),
            PushResult.QuotaBlocked => Problem("Monthly push quota exhausted.", statusCode: 503),
            PushResult.RateLimited => Problem("LINE rate limit active. Retry later.", statusCode: 429),
            PushResult.TargetNotFound => Problem("Target group not found or push not enabled.", statusCode: 404),
            _ => Problem("Push rejected.", statusCode: 502)
        };
    }

    [HttpGet("status")]
    public IActionResult Status()
    {
        if (!ValidateApiKey())
            return Problem("Unauthorized.", statusCode: 401);

        return Ok(new
        {
            quotaLevel = _push.GetQuotaLevel().ToString(),
            monthlyCount = _push.MonthlyPushCount,
            monthlyBudget = _push.MonthlyBudget
        });
    }

    private bool ValidateHmac(out string bodyString, out IActionResult? problem)
    {
        bodyString = string.Empty;
        problem = null;

        var secret = _config["App:PushApiSecret"];
        if (string.IsNullOrWhiteSpace(secret))
        {
            _logger.LogError("App:PushApiSecret not configured.");
            problem = Problem("Server configuration error.", statusCode: 500);
            return false;
        }

        var timestamp = Request.Headers["X-Push-Timestamp"].FirstOrDefault();
        var nonce = Request.Headers["X-Push-Nonce"].FirstOrDefault();
        var signature = Request.Headers["X-Push-Signature"].FirstOrDefault();

        if (string.IsNullOrEmpty(timestamp) || string.IsNullOrEmpty(nonce) || string.IsNullOrEmpty(signature))
        {
            problem = Problem("Missing authentication headers.", statusCode: 401);
            return false;
        }

        if (!long.TryParse(timestamp, out var ts))
        {
            problem = Problem("Invalid timestamp.", statusCode: 401);
            return false;
        }

        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        if (Math.Abs(now - ts) > 300)
        {
            problem = Problem("Request timestamp too old or too far in future.", statusCode: 401);
            return false;
        }

        Request.EnableBuffering();
        using var reader = new StreamReader(Request.Body, Encoding.UTF8, leaveOpen: true);
        bodyString = reader.ReadToEndAsync().GetAwaiter().GetResult();

        if (Encoding.UTF8.GetByteCount(bodyString) > MaxBodyBytes)
        {
            problem = Problem("Request body too large.", statusCode: 413);
            return false;
        }

        var message = $"{timestamp}.{nonce}.{bodyString}";
        var expectedBytes = HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), Encoding.UTF8.GetBytes(message));
        var expected = Convert.ToHexStringLower(expectedBytes);

        if (!CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(expected),
                Encoding.UTF8.GetBytes(signature)))
        {
            _logger.LogWarning("Push API HMAC validation failed.");
            problem = Problem("Invalid signature.", statusCode: 401);
            return false;
        }

        return true;
    }

    private bool ValidateApiKey()
    {
        var secret = _config["App:PushApiSecret"];
        if (string.IsNullOrWhiteSpace(secret))
            return false;

        var provided = Request.Headers["X-Push-Api-Key"].FirstOrDefault();
        if (string.IsNullOrEmpty(provided))
            return false;

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(secret),
            Encoding.UTF8.GetBytes(provided));
    }
}

public record PushRequest
{
    public string TargetId { get; init; } = string.Empty;
    public string Text { get; init; } = string.Empty;
}

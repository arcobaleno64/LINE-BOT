using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("api/line")]
public class LineWebhookController : ControllerBase
{
    private readonly string _channelSecret;
    private readonly IAiService _ai;
    private readonly LineReplyService _reply;
    private readonly ILogger<LineWebhookController> _logger;

    public LineWebhookController(
        IConfiguration config,
        IAiService ai,
        LineReplyService reply,
        ILogger<LineWebhookController> logger)
    {
        _channelSecret = config["Line:ChannelSecret"]
            ?? throw new InvalidOperationException("Missing Line:ChannelSecret");
        _ai     = ai;
        _reply  = reply;
        _logger = logger;
    }

    /// <summary>LINE Messaging API Webhook Endpoint</summary>
    [HttpPost("webhook")]
    public async Task<IActionResult> Webhook(CancellationToken ct)
    {
        // 1. 讀取 raw body
        using var reader = new StreamReader(Request.Body, Encoding.UTF8);
        var body = await reader.ReadToEndAsync(ct);

        // 2. 驗證 x-line-signature
        if (!VerifySignature(body, Request.Headers["x-line-signature"].ToString()))
        {
            _logger.LogWarning("Invalid LINE signature");
            return Unauthorized();
        }

        // 3. 反序列化
        var webhook = JsonSerializer.Deserialize<LineWebhookBody>(body);
        if (webhook?.Events is null || webhook.Events.Count == 0)
            return Ok();

        // 4. 處理每個 event（非同步 fire-and-forget，快速回 200 給 LINE）
        _ = Task.Run(async () =>
        {
            foreach (var evt in webhook.Events)
            {
                try
                {
                    await HandleEventAsync(evt, ct);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error handling event {EventId}", evt.WebhookEventId);
                }
            }
        }, ct);

        return Ok();
    }

    private async Task HandleEventAsync(LineEvent evt, CancellationToken ct)
    {
        // 只處理 text message，並套用 @mention gate
        if (!MentionGateService.ShouldHandle(evt))
            return;

        if (string.IsNullOrEmpty(evt.ReplyToken))
            return;

        // 移除 @mention 文字，取得使用者的真正訊息
        var userText = MentionGateService.StripMention(evt.Message!);
        if (string.IsNullOrWhiteSpace(userText))
        {
            await _reply.ReplyTextAsync(evt.ReplyToken, "請問有什麼我能幫忙的嗎？", ct);
            return;
        }

        _logger.LogInformation("Processing message from {UserId}: {Text}", evt.Source?.UserId, userText);

        // 呼叫 AI 取得回覆
        var aiReply = await _ai.GetReplyAsync(userText, ct);

        // 透過 LINE Reply API 回覆
        await _reply.ReplyTextAsync(evt.ReplyToken, aiReply, ct);
    }

    /// <summary>HMAC-SHA256 簽章驗證</summary>
    private bool VerifySignature(string body, string signature)
    {
        if (string.IsNullOrEmpty(signature))
            return false;

        var key  = Encoding.UTF8.GetBytes(_channelSecret);
        var data = Encoding.UTF8.GetBytes(body);

        using var hmac = new HMACSHA256(key);
        var hash = hmac.ComputeHash(data);
        var computed = Convert.ToBase64String(hash);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(computed),
            Encoding.UTF8.GetBytes(signature));
    }
}

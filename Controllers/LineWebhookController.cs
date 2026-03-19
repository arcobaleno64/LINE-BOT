using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("api/line")]
public class LineWebhookController(
    IConfiguration config,
    IAiService ai,
    LineReplyService reply,
    LineContentService content,
    ILogger<LineWebhookController> logger) : ControllerBase
{
    private readonly string _channelSecret = config["Line:ChannelSecret"]
            ?? throw new InvalidOperationException("Missing Line:ChannelSecret");
    private readonly IAiService _ai = ai;
    private readonly LineReplyService _reply = reply;
    private readonly LineContentService _content = content;
    private readonly ILogger<LineWebhookController> _logger = logger;


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
        }, CancellationToken.None);

        return Ok();
    }

    private async Task HandleEventAsync(LineEvent evt, CancellationToken ct)
    {
        if (evt.Type != "message" || evt.Message is null)
            return;

        if (string.IsNullOrEmpty(evt.ReplyToken))
            return;

        // 組合 user key：群組/聊天室 + 使用者 ID
        var sourceId = evt.Source?.GroupId ?? evt.Source?.RoomId ?? evt.Source?.UserId ?? "unknown";
        var userId = evt.Source?.UserId ?? "unknown";
        var userKey = $"{sourceId}:{userId}";

        if (evt.Message.Type == "text")
        {
            if (!MentionGateService.ShouldHandle(evt))
                return;

            var userText = MentionGateService.StripMention(evt.Message);
            if (string.IsNullOrWhiteSpace(userText))
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, "請問有什麼我能幫忙的嗎？", ct);
                return;
            }

            _logger.LogInformation("Processing text message from {UserId}: {Text}", evt.Source?.UserId, userText);
            var aiReply = await _ai.GetReplyAsync(userText, userKey, ct);
            await _reply.ReplyTextAsync(evt.ReplyToken, aiReply, ct);
            return;
        }

        if (evt.Message.Type == "image")
        {
            if (evt.Source?.Type is "group" or "room")
                return;

            _logger.LogInformation("Processing image message from {UserId}", evt.Source?.UserId);
            var (bytes, mimeType) = await _content.DownloadMessageContentAsync(evt.Message.Id, ct);
            var aiReply = await _ai.GetReplyFromImageAsync(bytes, mimeType, "請幫我分析這張圖片重點。", userKey, ct);
            await _reply.ReplyTextAsync(evt.ReplyToken, aiReply, ct);
            return;
        }

        if (evt.Message.Type == "file")
        {
            if (evt.Source?.Type is "group" or "room")
                return;

            _logger.LogInformation("Processing file message from {UserId}", evt.Source?.UserId);
            var (bytes, mimeType) = await _content.DownloadMessageContentAsync(evt.Message.Id, ct);
            var fileName = evt.Message.FileName ?? "uploaded-file";

            string extractedText;
            try
            {
                extractedText = _content.ExtractTextFromFile(bytes, fileName, mimeType);
            }
            catch (NotSupportedException)
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, "目前先支援文字型檔案（txt/md/csv/json/xml/log）。你也可以先把內容貼成文字，我可以馬上幫你整理。", ct);
                return;
            }

            var aiReply = await _ai.GetReplyFromDocumentAsync(fileName, mimeType, extractedText, "請幫我整理重點、關鍵結論與待辦事項。", userKey, ct);
            await _reply.ReplyTextAsync(evt.ReplyToken, aiReply, ct);
            return;
        }

        if (evt.Source?.Type == "user")
        {
            await _reply.ReplyTextAsync(evt.ReplyToken, "目前我支援文字、圖片與文字型檔案（txt/md/csv/json/xml/log）。", ct);
        }
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

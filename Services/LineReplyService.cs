using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

/// <summary>透過 LINE Messaging API 回覆訊息</summary>
public class LineReplyService
{
    private const string ReplyUrl = "https://api.line.me/v2/bot/message/reply";
    private readonly HttpClient _http;
    private readonly string _accessToken;

    public LineReplyService(HttpClient http, IConfiguration config)
    {
        _http        = http;
        _accessToken = config["Line:ChannelAccessToken"]
            ?? throw new InvalidOperationException("Missing Line:ChannelAccessToken");
    }

    /// <summary>回覆文字訊息</summary>
    public async Task ReplyTextAsync(string replyToken, string text, CancellationToken ct = default)
    {
        // LINE 文字訊息上限 5000 字
        if (text.Length > 5000)
            text = text[..4997] + "...";

        var payload = new
        {
            replyToken,
            messages = new[]
            {
                new { type = "text", text }
            }
        };

        var request = new HttpRequestMessage(HttpMethod.Post, ReplyUrl)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();
    }
}

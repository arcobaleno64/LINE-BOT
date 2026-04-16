using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

/// <summary>在 Bot 處理訊息期間顯示讀取動畫，提升使用者體驗。</summary>
public class LoadingIndicatorService
{
    private const string LoadingUrl = "https://api.line.me/v2/bot/chat/loading/start";

    private readonly HttpClient _http;
    private readonly string _accessToken;
    private readonly ILogger<LoadingIndicatorService> _logger;

    public LoadingIndicatorService(HttpClient http, IConfiguration config, ILogger<LoadingIndicatorService> logger)
    {
        _http = http;
        _accessToken = config["Line:ChannelAccessToken"]
            ?? throw new InvalidOperationException("Missing Line:ChannelAccessToken");
        _logger = logger;
    }

    /// <summary>
    /// 顯示讀取動畫。失敗不影響主流程。
    /// </summary>
    public async Task ShowAsync(LineEvent evt, CancellationToken ct = default)
    {
        var chatId = ResolveChatId(evt);
        if (chatId is null)
            return;

        var payload = new { chatId, loadingSeconds = 20 };
        var request = new HttpRequestMessage(HttpMethod.Post, LoadingUrl)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);

        try
        {
            using var response = await _http.SendAsync(request, ct);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogDebug(
                    "Loading indicator failed. StatusCode={StatusCode} SourceType={SourceType}",
                    (int)response.StatusCode,
                    evt.Source?.Type ?? "unknown");
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _logger.LogDebug(ex, "Loading indicator request failed. SourceType={SourceType}",
                evt.Source?.Type ?? "unknown");
        }
    }

    /// <summary>從事件源取得 chatId（groupId > roomId > userId）</summary>
    internal static string? ResolveChatId(LineEvent evt)
        => evt.Source?.GroupId ?? evt.Source?.RoomId ?? evt.Source?.UserId;
}

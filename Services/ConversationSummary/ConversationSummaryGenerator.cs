using System.Text;

namespace LineBotWebhook.Services;

public sealed class ConversationSummaryGenerator : IConversationSummaryGenerator
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _config;
    private readonly ILoggerFactory _loggerFactory;
    private readonly PersonaContext _persona;

    public ConversationSummaryGenerator(
        IHttpClientFactory httpClientFactory,
        IConfiguration config,
        ILoggerFactory loggerFactory,
        PersonaContext persona)
    {
        _httpClientFactory = httpClientFactory;
        _config = config;
        _loggerFactory = loggerFactory;
        _persona = persona;
    }

    public async Task<string> GenerateAsync(
        string? existingSummary,
        IReadOnlyList<ConversationHistoryService.ChatMessage> pendingMessages,
        CancellationToken ct = default)
    {
        var prompt = BuildPrompt(existingSummary, pendingMessages);
        var ai = new FailoverAiService(
            _httpClientFactory,
            _config,
            new ConversationHistoryService(maxRounds: 1, idleMinutes: 1),
            _loggerFactory,
            _persona,
            _loggerFactory.CreateLogger<FailoverAiService>());

        return await ai.GetReplyAsync(prompt, $"conversation-summary:{Guid.NewGuid():N}", ct);
    }

    private static string BuildPrompt(string? existingSummary, IReadOnlyList<ConversationHistoryService.ChatMessage> pendingMessages)
    {
        var transcript = new StringBuilder();
        foreach (var message in pendingMessages)
        {
            transcript.Append("- ")
                .Append(message.Role)
                .Append(": ")
                .AppendLine(message.Content);
        }

        return $"""
請將以下對話整理成精簡摘要，供後續對話延續使用。
請保留：
1. 已確認的事實
2. 使用者偏好或限制
3. 尚未完成的問題或待辦

如果某些資訊在對話中沒有明確提到，請不要補充或猜測。

現有摘要：
{(string.IsNullOrWhiteSpace(existingSummary) ? "（無）" : existingSummary)}

待整理對話：
{transcript.ToString().TrimEnd()}
""";
    }
}

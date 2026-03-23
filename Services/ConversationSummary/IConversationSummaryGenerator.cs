namespace LineBotWebhook.Services;

public interface IConversationSummaryGenerator
{
    Task<string> GenerateAsync(
        string? existingSummary,
        IReadOnlyList<ConversationHistoryService.ChatMessage> pendingMessages,
        CancellationToken ct = default);
}

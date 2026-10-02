namespace LineBotWebhook.Services;

public sealed record ConversationSummaryWorkItem(
    string UserKey,
    Guid SessionId,
    Guid SummaryId,
    string UserKeyFingerprint,
    DateTime EnqueuedAtUtc,
    int PendingCount,
    int MessageCount,
    string? UserKeyHash = null);
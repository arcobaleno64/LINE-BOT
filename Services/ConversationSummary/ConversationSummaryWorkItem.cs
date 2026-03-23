namespace LineBotWebhook.Services;

public sealed record ConversationSummaryWorkItem(
    string UserKey,
    string UserKeyFingerprint,
    DateTime EnqueuedAtUtc,
    int PendingCount,
    int MessageCount);

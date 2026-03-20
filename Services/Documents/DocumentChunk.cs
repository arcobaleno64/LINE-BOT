namespace LineBotWebhook.Services;

public sealed record DocumentChunk(
    int Index,
    int Start,
    int End,
    string Text);

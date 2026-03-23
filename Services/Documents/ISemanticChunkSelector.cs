namespace LineBotWebhook.Services;

public interface ISemanticChunkSelector
{
    Task<string> SelectRelevantTextAsync(IReadOnlyList<DocumentChunk> chunks, string userPrompt, CancellationToken ct = default);
}

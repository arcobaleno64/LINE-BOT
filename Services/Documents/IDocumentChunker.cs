namespace LineBotWebhook.Services;

public interface IDocumentChunker
{
    IReadOnlyList<DocumentChunk> ChunkText(string text);
}

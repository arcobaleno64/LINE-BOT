namespace LineBotWebhook.Services;

public sealed class DocumentChunker : IDocumentChunker
{
    private const int TargetChunkSize = 1500;
    private const int ChunkOverlap = 200;
    private const int BacktrackWindow = 160;

    public IReadOnlyList<DocumentChunk> Chunk(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return [];

        var normalized = text.Replace("\r\n", "\n").Trim();
        if (normalized.Length <= TargetChunkSize)
            return [new DocumentChunk(0, 0, normalized.Length, normalized)];

        var chunks = new List<DocumentChunk>();
        var start = 0;
        while (start < normalized.Length)
        {
            var idealEnd = Math.Min(normalized.Length, start + TargetChunkSize);
            var end = FindChunkEnd(normalized, start, idealEnd);
            if (end <= start)
                end = idealEnd;

            var chunkText = normalized[start..end].Trim();
            if (!string.IsNullOrWhiteSpace(chunkText))
            {
                chunks.Add(new DocumentChunk(
                    Index: chunks.Count,
                    Start: start,
                    End: end,
                    Text: chunkText));
            }

            if (end >= normalized.Length)
                break;

            var nextStart = Math.Max(0, end - ChunkOverlap);
            if (nextStart <= start)
                nextStart = end;

            start = nextStart;
        }

        return chunks;
    }

    private static int FindChunkEnd(string text, int start, int idealEnd)
    {
        if (idealEnd >= text.Length)
            return text.Length;

        var searchStart = Math.Max(start + 1, idealEnd - BacktrackWindow);
        for (var i = idealEnd - 1; i >= searchStart; i--)
        {
            if (i < text.Length - 1 && text[i] == '\n' && text[i + 1] == '\n')
                return i + 1;

            if (text[i] == '\n')
                return i + 1;

            if (char.IsWhiteSpace(text[i]))
                return i + 1;
        }

        return idealEnd;
    }

    public IReadOnlyList<DocumentChunk> ChunkText(string text) => Chunk(text);
}

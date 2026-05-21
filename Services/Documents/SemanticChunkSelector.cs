namespace LineBotWebhook.Services;

public sealed class SemanticChunkSelector(IEmbeddingService embeddings) : ISemanticChunkSelector
{
    private const int MaxSelectedChunks = 4;
    private const int MaxContextCharacters = 5200;
    internal const int MaxChunksToEmbed = 40;
    private readonly IEmbeddingService _embeddings = embeddings;

    public async Task<string> SelectRelevantTextAsync(IReadOnlyList<DocumentChunk> chunks, string userPrompt, CancellationToken ct = default)
    {
        if (chunks.Count == 0)
            return string.Empty;

        if (chunks.Count == 1)
            return chunks[0].Text;

        var candidates = chunks.Count <= MaxChunksToEmbed
            ? chunks
            : SampleEvenly(chunks, MaxChunksToEmbed);

        var queryEmbedding = await _embeddings.GetEmbeddingAsync(userPrompt, ct);
        var scored = new List<(DocumentChunk Chunk, double Score)>(candidates.Count);

        foreach (var chunk in candidates)
        {
            var chunkEmbedding = await _embeddings.GetEmbeddingAsync(chunk.Text, ct);
            scored.Add((chunk, CosineSimilarity(queryEmbedding, chunkEmbedding)));
        }

        var selected = scored
            .OrderByDescending(x => x.Score)
            .ThenBy(x => x.Chunk.Index)
            .Select(x => x.Chunk)
            .Take(MaxSelectedChunks)
            .ToArray();

        return BuildContext(selected);
    }

    private static string BuildContext(IEnumerable<DocumentChunk> chunks)
    {
        var selected = new List<DocumentChunk>();
        var totalChars = 0;
        foreach (var chunk in chunks.OrderBy(chunk => chunk.Index))
        {
            if (selected.Count > 0 && totalChars + chunk.Text.Length > MaxContextCharacters)
                break;

            selected.Add(chunk);
            totalChars += chunk.Text.Length;
        }

        return string.Join(
            "\n\n",
            selected.Select(chunk => $"[片段 {chunk.Index + 1}]\n{chunk.Text}"));
    }

    private static IReadOnlyList<DocumentChunk> SampleEvenly(IReadOnlyList<DocumentChunk> chunks, int targetCount)
    {
        var indexes = new SortedSet<int>();
        for (var i = 0; i < targetCount; i++)
        {
            var ratio = targetCount == 1 ? 0d : (double)i / (targetCount - 1);
            indexes.Add((int)Math.Round(ratio * (chunks.Count - 1)));
        }

        return indexes.Select(index => chunks[index]).ToArray();
    }

    private static double CosineSimilarity(IReadOnlyList<float> left, IReadOnlyList<float> right)
    {
        var length = Math.Min(left.Count, right.Count);
        if (length == 0)
            return 0d;

        double dot = 0;
        double leftNorm = 0;
        double rightNorm = 0;
        for (var i = 0; i < length; i++)
        {
            dot += left[i] * right[i];
            leftNorm += left[i] * left[i];
            rightNorm += right[i] * right[i];
        }

        if (leftNorm <= 0 || rightNorm <= 0)
            return 0d;

        return dot / (Math.Sqrt(leftNorm) * Math.Sqrt(rightNorm));
    }
}

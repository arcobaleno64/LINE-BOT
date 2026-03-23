namespace LineBotWebhook.Services;

public sealed class DocumentChunkSelector
{
    private const int MaxSelectedChunks = 4;
    private const int MaxContextCharacters = 5200;

    public IReadOnlyList<DocumentChunk> SelectForSummary(IReadOnlyList<DocumentChunk> chunks)
    {
        if (chunks.Count == 0)
            return [];

        if (chunks.Count <= MaxSelectedChunks)
            return ApplyContextBudget(chunks);

        var targetCount = Math.Min(MaxSelectedChunks, chunks.Count);
        var anchors = BuildCoverageAnchors(chunks, targetCount);
        return ApplyContextBudget(anchors.Select(index => chunks[index]));
    }

    public IReadOnlyList<DocumentChunk> SelectForQuestion(IReadOnlyList<DocumentChunk> chunks, string query)
    {
        if (chunks.Count == 0)
            return [];

        var queryTokens = Tokenize(query);
        if (queryTokens.Count == 0)
            return SelectForSummary(chunks);

        var ranked = chunks
            .Select(chunk => new
            {
                Chunk = chunk,
                Score = ScoreChunk(chunk, query, queryTokens)
            })
            .Where(x => x.Score > 0)
            .OrderByDescending(x => x.Score)
            .ThenBy(x => x.Chunk.Index)
            .Select(x => x.Chunk)
            .Take(MaxSelectedChunks)
            .ToArray();

        if (ranked.Length == 0)
            return ApplyContextBudget(chunks.Take(Math.Min(2, chunks.Count)));

        return ApplyContextBudget(ranked);
    }

    private static IReadOnlyList<DocumentChunk> ApplyContextBudget(IEnumerable<DocumentChunk> chunks)
    {
        var selected = new List<DocumentChunk>();
        var totalChars = 0;
        foreach (var chunk in chunks)
        {
            if (selected.Count > 0 && totalChars + chunk.Text.Length > MaxContextCharacters)
                break;

            selected.Add(chunk);
            totalChars += chunk.Text.Length;
        }

        return selected
            .OrderBy(chunk => chunk.Index)
            .ToArray();
    }

    private static double ScoreChunk(DocumentChunk chunk, string query, IReadOnlySet<string> queryTokens)
    {
        var score = 0d;
        var chunkTokens = Tokenize(chunk.Text);
        var matchedTokens = queryTokens.Count(token => chunkTokens.Contains(token));
        score += matchedTokens * 3d;

        var normalizedQuery = Normalize(query);
        var normalizedChunk = Normalize(chunk.Text);
        if (normalizedQuery.Length >= 2 && normalizedChunk.Contains(normalizedQuery, StringComparison.Ordinal))
            score += 6d;

        if (chunk.Text.Contains('#') || chunk.Text.Contains("- ") || chunk.Text.Contains("•"))
            score += matchedTokens > 0 ? 1.5d : 0d;

        var firstLine = chunk.Text.Split('\n', 2)[0];
        if (firstLine.Length <= 80 && queryTokens.Any(token => Normalize(firstLine).Contains(token, StringComparison.Ordinal)))
            score += 2d;

        return score;
    }

    private static SortedSet<int> BuildCoverageAnchors(IReadOnlyList<DocumentChunk> chunks, int targetCount)
    {
        var selectedIndexes = new SortedSet<int>();

        for (var i = 0; i < targetCount; i++)
        {
            var ratio = targetCount == 1 ? 0d : (double)i / (targetCount - 1);
            var index = (int)Math.Round(ratio * (chunks.Count - 1));
            selectedIndexes.Add(index);
        }

        var boostedCandidates = chunks
            .Select(chunk => new
            {
                chunk.Index,
                Score = ScoreSummaryChunk(chunk)
            })
            .Where(x => x.Score > 0)
            .OrderByDescending(x => x.Score)
            .ThenBy(x => x.Index)
            .Select(x => x.Index);

        foreach (var candidate in boostedCandidates)
        {
            if (selectedIndexes.Count >= targetCount)
                break;

            selectedIndexes.Add(candidate);
        }

        while (selectedIndexes.Count > targetCount)
        {
            var removable = selectedIndexes
                .Where(index => index != 0 && index != chunks.Count - 1)
                .OrderBy(index => ScoreSummaryChunk(chunks[index]))
                .FirstOrDefault();

            if (removable == 0 && !selectedIndexes.Contains(0))
                break;

            selectedIndexes.Remove(removable);
        }

        return selectedIndexes;
    }

    private static double ScoreSummaryChunk(DocumentChunk chunk)
    {
        var score = 0d;
        var lines = chunk.Text
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        if (lines.Length == 0)
            return score;

        var firstLine = lines[0];
        if (firstLine.Length <= 80 && (firstLine.Contains('#') || firstLine.Contains('：') || firstLine.Contains(':')))
            score += 4d;

        if (chunk.Text.Contains("- ", StringComparison.Ordinal)
            || chunk.Text.Contains("•", StringComparison.Ordinal)
            || chunk.Text.Contains("1.", StringComparison.Ordinal))
            score += 2d;

        if (chunk.Index == 0)
            score += 1.5d;

        return score;
    }

    private static HashSet<string> Tokenize(string text)
    {
        var tokens = new HashSet<string>(StringComparer.Ordinal);
        if (string.IsNullOrWhiteSpace(text))
            return tokens;

        var cjkBuffer = new List<char>();
        var word = new List<char>();
        foreach (var ch in Normalize(text))
        {
            if (IsCjk(ch))
            {
                FlushWord(tokens, word);
                cjkBuffer.Add(ch);
                continue;
            }

            FlushCjk(tokens, cjkBuffer);
            if (char.IsLetterOrDigit(ch))
            {
                word.Add(ch);
                continue;
            }

            FlushWord(tokens, word);
        }

        FlushCjk(tokens, cjkBuffer);
        FlushWord(tokens, word);
        return tokens;
    }

    private static void FlushWord(HashSet<string> tokens, List<char> word)
    {
        if (word.Count == 0)
            return;

        tokens.Add(new string([.. word]));
        word.Clear();
    }

    private static void FlushCjk(HashSet<string> tokens, List<char> chars)
    {
        if (chars.Count == 0)
            return;

        if (chars.Count == 1)
        {
            tokens.Add(chars[0].ToString());
            chars.Clear();
            return;
        }

        for (var i = 0; i < chars.Count - 1; i++)
            tokens.Add(new string([chars[i], chars[i + 1]]));

        chars.Clear();
    }

    private static string Normalize(string text)
    {
        var chars = text
            .ToLowerInvariant()
            .Select(ch => char.IsControl(ch) ? ' ' : ch)
            .ToArray();
        return new string(chars);
    }

    private static bool IsCjk(char ch)
        => ch is >= '\u4E00' and <= '\u9FFF';
}

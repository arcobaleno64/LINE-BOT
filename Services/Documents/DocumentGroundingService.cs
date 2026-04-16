namespace LineBotWebhook.Services;

public sealed class DocumentGroundingService
{
    private const string DefaultSummaryPrompt = "請幫我整理重點、關鍵結論與待辦事項。";

    private readonly DocumentChunker _chunker;
    private readonly DocumentChunkSelector _selector;
    private readonly ISemanticChunkSelector? _semanticSelector;
    private readonly ILogger<DocumentGroundingService>? _logger;

    public DocumentGroundingService(DocumentChunker chunker, DocumentChunkSelector selector)
    {
        _chunker = chunker;
        _selector = selector;
    }

    public DocumentGroundingService(
        DocumentChunker chunker,
        DocumentChunkSelector selector,
        ISemanticChunkSelector semanticSelector,
        ILogger<DocumentGroundingService> logger)
    {
        _chunker = chunker;
        _selector = selector;
        _semanticSelector = semanticSelector;
        _logger = logger;
    }

    public async Task<DocumentGroundingResult> PrepareAsync(string fileName, string mimeType, string extractedText, string? userPrompt = null, CancellationToken ct = default)
    {
        var chunks = _chunker.Chunk(extractedText);
        var mode = DetermineMode(userPrompt);
        var effectivePrompt = string.IsNullOrWhiteSpace(userPrompt) ? DefaultSummaryPrompt : userPrompt.Trim();
        var lexicalSelectedChunks = mode == DocumentTaskMode.QuestionAnswer
            ? _selector.SelectForQuestion(chunks, effectivePrompt)
            : _selector.SelectForSummary(chunks);

        if (lexicalSelectedChunks.Count == 0 && chunks.Count > 0)
            lexicalSelectedChunks = [chunks[0]];

        var selectedChunks = lexicalSelectedChunks;
        var selectedContext = BuildContext(selectedChunks);
        if (mode == DocumentTaskMode.QuestionAnswer && _semanticSelector is not null && chunks.Count > 1)
        {
            try
            {
                var semanticContext = await _semanticSelector.SelectRelevantTextAsync(chunks, effectivePrompt, ct);

                if (!string.IsNullOrWhiteSpace(semanticContext))
                {
                    selectedContext = semanticContext;
                    var semanticSelectedChunks = ResolveSelectedChunks(chunks, semanticContext);
                    if (semanticSelectedChunks.Count > 0)
                        selectedChunks = semanticSelectedChunks;
                }
            }
            catch (Exception ex)
            {
                _logger?.LogWarning(
                    "Document semantic selection failed. Falling back to lexical selection. RequestType={RequestType} Mode={Mode} ChunkCount={ChunkCount} HasSemanticSelector={HasSemanticSelector} HasFallback={HasFallback} StatusCode={StatusCode} ExceptionType={ExceptionType}",
                    "document",
                    mode,
                    chunks.Count,
                    _semanticSelector is not null,
                    true,
                    SensitiveLogHelpers.GetStatusCode(ex),
                    SensitiveLogHelpers.GetFailureType(ex));
            }
        }

        var groundedPrompt = mode == DocumentTaskMode.QuestionAnswer
            ? BuildQuestionAnswerPrompt(fileName, mimeType, effectivePrompt)
            : BuildSummaryPrompt(fileName, mimeType, effectivePrompt);

        return new DocumentGroundingResult(
            mode,
            chunks,
            selectedChunks,
            selectedContext,
            groundedPrompt);
    }

    private static string BuildContext(IReadOnlyList<DocumentChunk> chunks)
    {
        return string.Join(
            "\n\n",
            chunks.Select(chunk => $"[片段 {chunk.Index + 1}]\n{chunk.Text}"));
    }

    private static IReadOnlyList<DocumentChunk> ResolveSelectedChunks(IReadOnlyList<DocumentChunk> chunks, string context)
    {
        var matches = System.Text.RegularExpressions.Regex.Matches(context, @"\[片段\s+(?<index>\d+)\]");
        if (matches.Count == 0)
            return [];

        var indexes = matches
            .Select(match => int.TryParse(match.Groups["index"].Value, out var value) ? value - 1 : -1)
            .Where(index => index >= 0 && index < chunks.Count)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();

        return indexes.Select(index => chunks[index]).ToArray();
    }

    private static DocumentTaskMode DetermineMode(string? userPrompt)
    {
        if (string.IsNullOrWhiteSpace(userPrompt))
            return DocumentTaskMode.Summary;

        var normalized = userPrompt.Trim();
        if (normalized.Contains('?') || normalized.Contains('？'))
            return DocumentTaskMode.QuestionAnswer;

        var questionHints = new[]
        {
            "請問", "是否", "誰", "何時", "哪裡", "多少", "多久", "截止", "提到", "負責", "有沒有", "什麼"
        };

        return questionHints.Any(hint => normalized.Contains(hint, StringComparison.Ordinal))
            ? DocumentTaskMode.QuestionAnswer
            : DocumentTaskMode.Summary;
    }

    private static string BuildSummaryPrompt(string fileName, string mimeType, string userPrompt)
    {
        return $"""
請只根據我提供的文件片段整理內容，不要補充片段中沒有出現的事實。
若片段不足以支持某項結論，請明確寫出「未明確提及」或「無法確認」，不可自行補完。

文件資訊：
- 檔名：{fileName}
- 類型：{mimeType}

請依使用者需求整理：
{userPrompt}

請至少輸出：
1. 重點
2. 關鍵結論
3. 待辦事項
""";
    }

    private static string BuildQuestionAnswerPrompt(string fileName, string mimeType, string userPrompt)
    {
        return $"""
請只根據我提供的文件片段回答問題，不要猜測或補完片段中沒有的事實。
若目前片段不足以回答，請直接說「根據目前提供的文件片段，無法確認」。
不得使用常識、慣例或上下文推測補完答案。

文件資訊：
- 檔名：{fileName}
- 類型：{mimeType}

問題：
{userPrompt}

若能回答，請直接回答；必要時可附上簡短的「依據片段」或片段編號。
""";
    }
}

public sealed record DocumentGroundingResult(
    DocumentTaskMode Mode,
    IReadOnlyList<DocumentChunk> AllChunks,
    IReadOnlyList<DocumentChunk> SelectedChunks,
    string SelectedContext,
    string GroundedPrompt);

public enum DocumentTaskMode
{
    Summary,
    QuestionAnswer
}

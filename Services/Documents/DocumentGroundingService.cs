namespace LineBotWebhook.Services;

public sealed class DocumentGroundingService
{
    private const string DefaultSummaryPrompt = "請幫我整理重點、關鍵結論與待辦事項。";

    private readonly DocumentChunker _chunker;
    private readonly DocumentChunkSelector _selector;

    public DocumentGroundingService(DocumentChunker chunker, DocumentChunkSelector selector)
    {
        _chunker = chunker;
        _selector = selector;
    }

    public DocumentGroundingResult Prepare(string fileName, string mimeType, string extractedText, string? userPrompt = null)
    {
        var chunks = _chunker.Chunk(extractedText);
        var mode = DetermineMode(userPrompt);
        var effectivePrompt = string.IsNullOrWhiteSpace(userPrompt) ? DefaultSummaryPrompt : userPrompt.Trim();
        var selectedChunks = mode == DocumentTaskMode.QuestionAnswer
            ? _selector.SelectForQuestion(chunks, effectivePrompt)
            : _selector.SelectForSummary(chunks);

        if (selectedChunks.Count == 0 && chunks.Count > 0)
            selectedChunks = [chunks[0]];

        var selectedContext = string.Join(
            "\n\n",
            selectedChunks.Select(chunk => $"[片段 {chunk.Index + 1}]\n{chunk.Text}"));

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
若片段不足以支持某項結論，請明確寫出「未明確提及」。

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

文件資訊：
- 檔名：{fileName}
- 類型：{mimeType}

問題：
{userPrompt}

若能回答，請直接回答；必要時可附上「依據片段」說明。
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

using System.Net;
using System.Text;
using LineBotWebhook.Models;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class DocumentPipelineTests
{
    [Fact]
    public void Chunker_ShortDocument_ReturnsSingleChunk()
    {
        var chunker = new DocumentChunker();

        var chunks = chunker.Chunk("這是一份很短的文件。\n只有兩行。");

        var chunk = Assert.Single(chunks);
        Assert.Contains("這是一份很短的文件", chunk.Text, StringComparison.Ordinal);
    }

    [Fact]
    public void Chunker_LongDocument_ReturnsMultipleChunks()
    {
        var chunker = new DocumentChunker();
        var text = BuildLongDocument(40, "一般段落內容");

        var chunks = chunker.Chunk(text);

        Assert.True(chunks.Count >= 3);
        Assert.All(chunks, chunk => Assert.False(string.IsNullOrWhiteSpace(chunk.Text)));
        Assert.True(chunks[1].Start < chunks[0].End);
    }

    [Fact]
    public void Selector_QueryAwareSelection_PrefersRelevantChunk()
    {
        var selector = new DocumentChunkSelector();
        var chunks = new[]
        {
            new DocumentChunk(0, 0, 10, "這段是在講公司沿革與背景。"),
            new DocumentChunk(1, 11, 20, "付款條件：簽約後 30 日內完成付款，逾期需支付違約金。"),
            new DocumentChunk(2, 21, 30, "這段是在講附錄與其他一般說明。")
        };

        var selected = selector.SelectForQuestion(chunks, "合約中誰負責付款？付款條件是什麼？");

        Assert.Contains(selected, chunk => chunk.Index == 1);
        Assert.True(selected.Count < chunks.Length);
    }

    [Fact]
    public void GroundingService_SummaryMode_UsesRepresentativeChunks_NotFullDocument()
    {
        var service = new DocumentGroundingService(new DocumentChunker(), new DocumentChunkSelector());
        var text = BuildLongDocument(40, "這是摘要模式測試內容");

        var result = service.Prepare("report.txt", "text/plain", text, "請幫我整理重點、關鍵結論與待辦事項。");

        Assert.Equal(DocumentTaskMode.Summary, result.Mode);
        Assert.True(result.AllChunks.Count > 1);
        Assert.True(result.SelectedChunks.Count > 1);
        Assert.True(result.SelectedChunks.Count < result.AllChunks.Count);
        Assert.Contains("請只根據我提供的文件片段整理內容", result.GroundedPrompt, StringComparison.Ordinal);
    }

    [Fact]
    public void GroundingService_EmptyDocument_ReturnsNoChunks_ButKeepsGroundedPrompt()
    {
        var service = new DocumentGroundingService(new DocumentChunker(), new DocumentChunkSelector());

        var result = service.Prepare("empty.txt", "text/plain", "   ", "請幫我整理重點、關鍵結論與待辦事項。");

        Assert.Empty(result.AllChunks);
        Assert.Empty(result.SelectedChunks);
        Assert.Equal(string.Empty, result.SelectedContext);
        Assert.Equal(DocumentTaskMode.Summary, result.Mode);
        Assert.Contains("請只根據我提供的文件片段整理內容", result.GroundedPrompt, StringComparison.Ordinal);
    }

    [Fact]
    public void GroundingService_QuestionMode_UsesQueryAwareSelection_AndConservativePrompt()
    {
        var service = new DocumentGroundingService(new DocumentChunker(), new DocumentChunkSelector());
        var text = """
第一節：會議背景與摘要。

第二節：截止日為 2026-03-31，負責人是小王。

第三節：其他補充資訊。
""";

        var result = service.Prepare("meeting.md", "text/markdown", text, "這份文件提到的截止日是什麼？");

        Assert.Equal(DocumentTaskMode.QuestionAnswer, result.Mode);
        Assert.Contains("截止日", result.SelectedContext, StringComparison.Ordinal);
        Assert.Contains("無法確認", result.GroundedPrompt, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("a.txt")]
    [InlineData("a.md")]
    [InlineData("a.csv")]
    [InlineData("a.json")]
    [InlineData("a.xml")]
    [InlineData("a.log")]
    public void ExtractTextFromFile_TextFormats_RemainSupported(string fileName)
    {
        var service = new LineContentService(new HttpClient(new RecordingHttpMessageHandler((request, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)))), TestFactory.BuildConfig());

        var text = service.ExtractTextFromFile(Encoding.UTF8.GetBytes("hello"), fileName, "text/plain");

        Assert.Equal("hello", text);
    }

    [Fact]
    public async Task FileHandler_UsesChunkBasedPipeline_AndPreservesDownloadReply()
    {
        var captured = new List<(string ExtractedText, string Prompt)>();
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService
        {
            OnFileAsync = (name, mime, text, prompt, userKey, ct) =>
            {
                captured.Add((text, prompt));
                return Task.FromResult("整理完成");
            }
        };
        var longText = string.Join(
            "\n\n",
            Enumerable.Range(1, 48).Select(i =>
                $"第{i}節：這是很長的文件段落，包含不同條款、日期、責任與待辦事項。這一節也補充了專案背景、交付項目、付款條件、風險說明與後續行動建議。"));

        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me", StringComparison.Ordinal))
            {
                var response = new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent(Encoding.UTF8.GetBytes(longText))
                };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/plain");
                return Task.FromResult(response);
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        });

        var fileHandler = TestFactory.CreateFileHandler(config, ai, handler);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "file", FileName = "a.txt" }
        };

        await fileHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var aiCall = Assert.Single(captured);
        Assert.Contains("[片段", aiCall.ExtractedText, StringComparison.Ordinal);
        Assert.NotEqual(longText, aiCall.ExtractedText);
        Assert.Contains("請只根據我提供的文件片段整理內容", aiCall.Prompt, StringComparison.Ordinal);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("下載整理檔", replyText!, StringComparison.Ordinal);
        Assert.Contains("https://unit.test/downloads/", replyText!, StringComparison.Ordinal);
    }

    private static string BuildLongDocument(int paragraphs, string marker)
    {
        return string.Join(
            "\n\n",
            Enumerable.Range(1, paragraphs).Select(i =>
                $"第{i}段 {marker}。這裡有一些補充說明、條列事項與日期 2026-03-{(i % 28) + 1:00}。此外還包含會議背景、責任分工、付款條件、交付期限與待辦事項。"
                + " 本段也會提到風險說明、驗收標準、交付清單、角色分工與需要追蹤的決策。"
                + " 為了測試長文件切塊，這裡再補上一段描述，說明專案背景、預算限制、重要里程碑與跨部門協作安排。"));
    }
}

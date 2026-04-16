using System.Net;
using System.Text;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class FileFallbackTests
{
    [Fact]
    public async Task GroundingService_WhenSemanticSelectorThrows_FallsBackToLexicalSelection()
    {
        var selector = new FakeSemanticChunkSelector
        {
            OnSelectAsync = (chunks, prompt, ct) => throw new HttpRequestException("embedding down")
        };
        var service = new DocumentGroundingService(
            new DocumentChunker(),
            new DocumentChunkSelector(),
            selector,
            NullLogger<DocumentGroundingService>.Instance);
        var text = BuildLongDocument();

        var result = await service.PrepareAsync("report.txt", "text/plain", text, "請幫我整理重點、關鍵結論與待辦事項。");

        Assert.True(result.AllChunks.Count > 1);
        Assert.NotEmpty(result.SelectedChunks);
        Assert.NotEmpty(result.SelectedContext);
        Assert.Contains("[片段", result.SelectedContext, StringComparison.Ordinal);
    }

    [Fact]
    public async Task FileHandler_WhenSemanticSelectorThrows_StillCompletesReply()
    {
        var captured = new List<string>();
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService
        {
            OnTextAsync = (message, userKey, ct, enableQuickReplies) =>
            {
                captured.Add(message);
                return Task.FromResult("整理完成");
            }
        };
        var documents = new DocumentGroundingService(
            new DocumentChunker(),
            new DocumentChunkSelector(),
            new FakeSemanticChunkSelector
            {
                OnSelectAsync = (chunks, prompt, ct) => throw new HttpRequestException("embedding down")
            },
            NullLogger<DocumentGroundingService>.Instance);

        var longText = BuildLongDocument();
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

        var fileHandler = TestFactory.CreateFileHandler(config, ai, handler, documents: documents);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "file", FileName = "a.txt" }
        };

        await fileHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var aiCall = Assert.Single(captured);
        Assert.Contains("[片段", aiCall, StringComparison.Ordinal);
        Assert.Contains("請只根據我提供的文件片段整理內容", aiCall, StringComparison.Ordinal);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("下載整理檔", replyText!, StringComparison.Ordinal);
    }

    private static string BuildLongDocument()
    {
        return string.Join(
            "\n\n",
            Enumerable.Range(1, 32).Select(i =>
                $"第{i}段：這是很長的文件內容，包含專案背景、交付事項、待辦事項與關鍵結論。"
                + " 此外也補充了付款條件、時程安排、責任分工、風險提醒與後續追蹤事項。"
                + " 這段文字故意拉長，確保文件會先切 chunk，再進入 grounding 與 fallback。"));
    }
}

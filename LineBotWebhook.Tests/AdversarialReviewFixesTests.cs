using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Threading.Channels;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

/// <summary>
/// Regression tests covering fixes from the adversarial review round 1.
/// </summary>
public class AdversarialReviewFixesTests
{
    // ── HIGH: SemanticChunkSelector caps embedding calls regardless of input size ──

    [Fact]
    public async Task SemanticChunkSelector_OverCap_LimitsEmbeddingCalls()
    {
        var embeddings = new CountingEmbeddingService();
        var selector = new SemanticChunkSelector(embeddings);

        var chunkCount = SemanticChunkSelector.MaxChunksToEmbed * 10;
        var chunks = Enumerable
            .Range(0, chunkCount)
            .Select(i => new DocumentChunk(i, i * 10, (i + 1) * 10, $"片段內容 {i}"))
            .ToArray();

        var _ = await selector.SelectRelevantTextAsync(chunks, "問題");

        // 1 query embedding + at most MaxChunksToEmbed chunk embeddings
        Assert.True(
            embeddings.CallCount <= SemanticChunkSelector.MaxChunksToEmbed + 1,
            $"Expected at most {SemanticChunkSelector.MaxChunksToEmbed + 1} embedding calls, got {embeddings.CallCount}.");
    }

    // ── MEDIUM: LineContentService rejects oversized files before initiating HTTP download ──

    [Fact]
    public async Task DownloadMessageContentAsync_ExpectedSizeOverLimit_ThrowsBeforeHttpCall()
    {
        var probe = new ProbingHandler();
        var http = new HttpClient(probe);
        var cfg = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Line:ChannelAccessToken"] = "fake-token",
                ["App:MaxFileSizeBytes"] = "1024"
            })
            .Build();
        var svc = new LineContentService(http, cfg);

        await Assert.ThrowsAsync<NotSupportedException>(() =>
            svc.DownloadMessageContentAsync("msg-1", expectedSize: 5 * 1024));

        Assert.Equal(0, probe.SendCount);
    }

    // ── R2 MEDIUM: HttpResponseMessage is disposed on size-rejection path ──

    [Fact]
    public async Task DownloadMessageContentAsync_OversizeContentLength_DisposesResponse()
    {
        var probe = new DisposeTrackingHandler(payloadSize: 5 * 1024);
        var http = new HttpClient(probe);
        var cfg = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Line:ChannelAccessToken"] = "fake-token",
                ["App:MaxFileSizeBytes"] = "1024"
            })
            .Build();
        var svc = new LineContentService(http, cfg);

        await Assert.ThrowsAsync<NotSupportedException>(() =>
            svc.DownloadMessageContentAsync("msg-2"));

        Assert.True(probe.LastResponseDisposed, "Response should be disposed on rejection path");
    }

    // ── R2 MEDIUM: Semantic candidate set retains lexical hits when over cap ──

    [Fact]
    public async Task GroundingService_LargeDocument_SemanticReceivesLexicalHits()
    {
        var embeddings = new TestHelpers_FakeEmbeddingService();
        var semantic = new SemanticChunkSelector(embeddings);
        var captured = new RecordingSemanticChunkSelector(semantic);

        var grounding = new DocumentGroundingService(
            new DocumentChunker(),
            new DocumentChunkSelector(),
            captured,
            NullLogger<DocumentGroundingService>.Instance);

        var text = string.Join("\n\n", Enumerable.Range(0, 200)
            .Select(i => i == 137
                ? "[特殊片段] 付款條件：簽約後三十日內。"
                : $"段落 {i}：一般背景說明。"));

        await grounding.PrepareAsync("doc.txt", "text/plain", text, "付款條件是什麼？");

        Assert.NotNull(captured.LastInput);
        var capturedIndexes = captured.LastInput!.Select(chunk => chunk.Index).ToHashSet();

        // The lexical selector should have found the "[特殊片段]" chunk; that chunk's index
        // must appear in the candidate set passed to the semantic selector.
        var lexicalSelector = new DocumentChunkSelector();
        var allChunks = new DocumentChunker().Chunk(text);
        var lexicalSelected = lexicalSelector.SelectForQuestion(allChunks, "付款條件是什麼？");
        Assert.NotEmpty(lexicalSelected);
        Assert.All(lexicalSelected, chunk =>
            Assert.Contains(chunk.Index, capturedIndexes));
    }

    // ── R2 LOW: Image handler replies to size-limit error instead of throwing to worker ──
    //   Covered via DocumentPipelineTests/FileFallbackTests style would require full handler
    //   wiring; this regression is asserted by the change being present and other handlers'
    //   identical pattern. (No additional unit test added to avoid handler-mock churn.)

    // ── R3 MEDIUM: WebhookBackgroundService drops stale items past replyToken validity ──

    [Fact]
    public async Task BackgroundService_StaleQueueItem_DroppedBeforeDispatch()
    {
        var queue = new ManualBackgroundQueue();
        var dispatcher = new RecordingDispatcher();
        var svc = new WebhookBackgroundService(queue, dispatcher, NullLogger<WebhookBackgroundService>.Instance);

        var staleItem = new WebhookQueueItem(new Models.LineEvent { WebhookEventId = "stale" }, "https://x")
        {
            EnqueuedAt = DateTimeOffset.UtcNow - WebhookBackgroundService.MaxQueueAge - TimeSpan.FromSeconds(5)
        };
        var freshItem = new WebhookQueueItem(new Models.LineEvent { WebhookEventId = "fresh" }, "https://x");

        Assert.True(queue.TryEnqueue(staleItem));
        Assert.True(queue.TryEnqueue(freshItem));
        queue.Complete();

        await svc.StartAsync(CancellationToken.None);
        await dispatcher.WaitForDispatchAsync(timeoutMs: 2000);
        await svc.StopAsync(CancellationToken.None);

        Assert.Single(dispatcher.DispatchedEventIds);
        Assert.Equal("fresh", dispatcher.DispatchedEventIds[0]);
    }

    // ── R3 MEDIUM: QuickReply suggestion length respects LINE 20-char limit ──

    [Fact]
    public void QuickReplySuggestionParser_LongSuggestion_Rejected()
    {
        var twentyOne = new string('字', 21);
        var input = $"答覆\n<quick-replies>[\"{twentyOne}\",\"短\"]</quick-replies>";

        var result = QuickReplySuggestionParser.Parse(input);

        Assert.DoesNotContain(twentyOne, result.Suggestions);
        Assert.Contains("短", result.Suggestions);
    }

    // ── R3 MEDIUM: Office text extraction rejects after MaxExtractedTextChars accumulated ──

    [Fact]
    public void ExtractTextFromDocx_AccumulatedTextOverLimit_Throws()
    {
        var bigParagraph = new string('文', LineContentService.MaxExtractedTextChars + 100);
        var docx = LineContentServiceTests_BuildBigDocx(bigParagraph);

        var ex = Assert.Throws<NotSupportedException>(() =>
            LineContentService.ExtractTextFromDocx(docx));

        Assert.Contains("過大", ex.Message, StringComparison.Ordinal);
    }

    // ── R5 MEDIUM: OOXML part decompressed-size pre-check rejects zip bombs before DOM parse ──

    [Fact]
    public void EnsureOoxmlPartSizes_OversizedPart_Throws()
    {
        var oversized = BuildZipWithOversizedPart(
            (int)(LineContentService.MaxOoxmlPartDecompressedBytes + 1024));

        var ex = Assert.Throws<NotSupportedException>(() =>
            LineContentService.EnsureOoxmlPartSizesWithinLimit(oversized));

        Assert.Contains("分件過大", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void EnsureOoxmlPartSizes_AllPartsUnderLimit_DoesNotThrow()
    {
        var safe = LineContentServiceTests_BuildBigDocx("ordinary content");
        LineContentService.EnsureOoxmlPartSizesWithinLimit(safe);
    }

    // ── Self-audit: ConversationHistoryService.Append must prune so writes alone cannot
    //                 grow _sessions beyond MaxSessions ──

    [Fact]
    public void ConversationHistory_AppendOnly_PrunesBeyondMaxSessions()
    {
        var history = new ConversationHistoryService(maxRounds: 1, idleMinutes: -1);

        // MaxSessions=1000 internally; create 1500 distinct users via Append only.
        for (var i = 0; i < 1500; i++)
            history.Append($"user-{i}", "hi", "ok");

        var snapshot = history.GetType()
            .GetField("_sessions", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!
            .GetValue(history) as System.Collections.IDictionary;
        Assert.NotNull(snapshot);
        Assert.True(snapshot!.Count <= 1000, $"Expected sessions to be capped at 1000, got {snapshot.Count}.");
    }

    private static byte[] BuildZipWithOversizedPart(int decompressedBytes)
    {
        using var ms = new MemoryStream();
        using (var zip = new ZipArchive(ms, ZipArchiveMode.Create, leaveOpen: true))
        {
            var entry = zip.CreateEntry("word/document.xml", CompressionLevel.Optimal);
            using var stream = entry.Open();
            // Highly compressible payload — small zip, huge decompressed size.
            var buffer = new byte[8192];
            var written = 0;
            while (written < decompressedBytes)
            {
                var chunk = Math.Min(buffer.Length, decompressedBytes - written);
                stream.Write(buffer, 0, chunk);
                written += chunk;
            }
        }
        return ms.ToArray();
    }

    // ── MEDIUM: WebhookEventDeduplicationService is atomic under concurrency ──

    [Fact]
    public async Task TryMarkSeen_ConcurrentSameEventId_OnlyOneWins()
    {
        using var svc = new WebhookEventDeduplicationService();
        const string eventId = "concurrent-evt";
        const int callers = 64;

        var gate = new TaskCompletionSource();
        var tasks = Enumerable.Range(0, callers).Select(_ => Task.Run(async () =>
        {
            await gate.Task;
            return svc.TryMarkSeen(eventId);
        })).ToArray();

        gate.SetResult();
        var results = await Task.WhenAll(tasks);

        Assert.Equal(1, results.Count(r => r));
    }

    // ── Helpers ────────────────────────────────────────────────────────────────

    private sealed class CountingEmbeddingService : IEmbeddingService
    {
        public int CallCount { get; private set; }

        public Task<IReadOnlyList<float>> GetEmbeddingAsync(string text, CancellationToken ct = default)
        {
            CallCount++;
            return Task.FromResult<IReadOnlyList<float>>(new float[] { 1f, 0f, 0f });
        }
    }

    private sealed class ProbingHandler : HttpMessageHandler
    {
        public int SendCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            SendCount++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent([])
                {
                    Headers = { ContentType = new MediaTypeHeaderValue("application/octet-stream") }
                }
            });
        }
    }

    private sealed class DisposeTrackingHandler(int payloadSize) : HttpMessageHandler
    {
        public bool LastResponseDisposed { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var payload = new byte[payloadSize];
            var content = new ByteArrayContent(payload);
            content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
            content.Headers.ContentLength = payloadSize;
            var response = new TrackingHttpResponseMessage(HttpStatusCode.OK, () => LastResponseDisposed = true)
            {
                Content = content
            };
            return Task.FromResult<HttpResponseMessage>(response);
        }
    }

    private sealed class TrackingHttpResponseMessage(HttpStatusCode statusCode, Action onDispose)
        : HttpResponseMessage(statusCode)
    {
        protected override void Dispose(bool disposing)
        {
            base.Dispose(disposing);
            if (disposing)
                onDispose();
        }
    }

    private sealed class TestHelpers_FakeEmbeddingService : IEmbeddingService
    {
        public Task<IReadOnlyList<float>> GetEmbeddingAsync(string text, CancellationToken ct = default)
            => Task.FromResult<IReadOnlyList<float>>(new float[] { 1f, 0f, 0f });
    }

    private sealed class RecordingSemanticChunkSelector(ISemanticChunkSelector inner) : ISemanticChunkSelector
    {
        public IReadOnlyList<DocumentChunk>? LastInput { get; private set; }

        public Task<string> SelectRelevantTextAsync(IReadOnlyList<DocumentChunk> chunks, string userPrompt, CancellationToken ct = default)
        {
            LastInput = chunks;
            return inner.SelectRelevantTextAsync(chunks, userPrompt, ct);
        }
    }

    private sealed class ManualBackgroundQueue : IWebhookBackgroundQueue
    {
        private readonly Channel<WebhookQueueItem> _channel = Channel.CreateUnbounded<WebhookQueueItem>();

        public bool TryEnqueue(WebhookQueueItem item) => _channel.Writer.TryWrite(item);

        public IAsyncEnumerable<WebhookQueueItem> DequeueAllAsync(CancellationToken cancellationToken)
            => _channel.Reader.ReadAllAsync(cancellationToken);

        public WebhookQueueSnapshot GetSnapshot() => new(0, 0, 0, 0, 0);

        public void Complete() => _channel.Writer.TryComplete();
    }

    private sealed class RecordingDispatcher : ILineWebhookDispatcher
    {
        private readonly TaskCompletionSource _dispatched = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public List<string> DispatchedEventIds { get; } = new();

        public Task DispatchAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
        {
            DispatchedEventIds.Add(evt.WebhookEventId);
            _dispatched.TrySetResult();
            return Task.CompletedTask;
        }

        public Task WaitForDispatchAsync(int timeoutMs)
            => Task.WhenAny(_dispatched.Task, Task.Delay(timeoutMs));
    }

    internal static byte[] LineContentServiceTests_BuildBigDocx(string paragraphText)
    {
        using var ms = new MemoryStream();
        using (var zip = new ZipArchive(ms, ZipArchiveMode.Create, leaveOpen: true))
        {
            AddEntry(zip, "[Content_Types].xml", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
""");
            AddEntry(zip, "_rels/.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
""");
            AddEntry(zip, "word/_rels/document.xml.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>
""");
            var doc = new StringBuilder("""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
""");
            // Split paragraphText into ~10k-char paragraphs to bypass per-paragraph XML overhead.
            const int chunk = 10_000;
            for (var i = 0; i < paragraphText.Length; i += chunk)
            {
                var piece = paragraphText.AsSpan(i, Math.Min(chunk, paragraphText.Length - i)).ToString();
                doc.Append("<w:p><w:r><w:t>")
                   .Append(System.Security.SecurityElement.Escape(piece))
                   .Append("</w:t></w:r></w:p>");
            }
            doc.Append("</w:body></w:document>");
            AddEntry(zip, "word/document.xml", doc.ToString());
        }
        return ms.ToArray();
    }

    private static void AddEntry(ZipArchive zip, string path, string content)
    {
        var entry = zip.CreateEntry(path);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        writer.Write(content);
    }
}

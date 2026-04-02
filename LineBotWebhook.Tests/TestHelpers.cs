using System.Net;
using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

internal sealed class RecordingHttpMessageHandler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> responder)
    : HttpMessageHandler
{
    public List<HttpRequestMessage> Requests { get; } = [];

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests.Add(request);
        return await responder(request, cancellationToken);
    }
}

internal sealed class FakeAiService : IAiService
{
    public int TextCalls { get; private set; }
    public int ImageCalls { get; private set; }
    public int FileCalls { get; private set; }

    public Func<string, string, CancellationToken, bool, Task<string>> OnTextAsync { get; set; }
        = (msg, key, ct, enableQuickReplies) => Task.FromResult("AI-OK");

    public Func<byte[], string, string, string, CancellationToken, Task<string>> OnImageAsync { get; set; }
        = (bytes, mime, prompt, key, ct) => Task.FromResult("IMG-OK");

    public Func<string, string, string, string, string, CancellationToken, Task<string>> OnFileAsync { get; set; }
        = (fileName, mime, text, prompt, key, ct) => Task.FromResult("FILE-OK");

    public Func<string, CancellationToken, Task<string>> OnStatelessAsync { get; set; }
        = (prompt, ct) => Task.FromResult("STATELESS-OK");

    public Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default, bool enableQuickReplies = false)
    {
        TextCalls++;
        return OnTextAsync(userMessage, userKey, ct, enableQuickReplies);
    }

    public Task<string> GetReplyFromImageAsync(byte[] imageBytes, string mimeType, string userPrompt, string userKey, CancellationToken ct = default)
    {
        ImageCalls++;
        return OnImageAsync(imageBytes, mimeType, userPrompt, userKey, ct);
    }

    public Task<string> GetReplyFromDocumentAsync(string fileName, string mimeType, string extractedText, string userPrompt, string userKey, CancellationToken ct = default)
    {
        FileCalls++;
        return OnFileAsync(fileName, mimeType, extractedText, userPrompt, userKey, ct);
    }

    public Task<string> GenerateStatelessReplyAsync(string prompt, CancellationToken ct = default)
    {
        return OnStatelessAsync(prompt, ct);
    }
}

internal sealed class FakeDispatcher : ILineWebhookDispatcher
{
    private readonly TaskCompletionSource<bool> _firstDispatchTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly List<(LineEvent Event, string PublicBaseUrl)> _dispatches = [];

    public int DispatchCalls { get; private set; }
    public IReadOnlyList<(LineEvent Event, string PublicBaseUrl)> Dispatches => _dispatches;
    public Func<LineEvent, string, CancellationToken, Task>? OnDispatchAsync { get; set; }

    public async Task DispatchAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        DispatchCalls++;
        _dispatches.Add((evt, publicBaseUrl));
        _firstDispatchTcs.TrySetResult(true);
        if (OnDispatchAsync is not null)
            await OnDispatchAsync(evt, publicBaseUrl, ct);
    }

    public async Task<bool> WaitForDispatchAsync(TimeSpan timeout)
    {
        var completed = await Task.WhenAny(_firstDispatchTcs.Task, Task.Delay(timeout));
        return completed == _firstDispatchTcs.Task;
    }
}

internal sealed class FakeWebhookBackgroundQueue : IWebhookBackgroundQueue
{
    private readonly List<WebhookQueueItem> _items = [];

    public bool TryEnqueueResult { get; set; } = true;
    public int CompleteCalls { get; private set; }
    public IReadOnlyList<WebhookQueueItem> Items => _items;
    public WebhookQueueSnapshot Snapshot { get; set; } = new(0, 256, 0, 0, 0);

    public bool TryEnqueue(WebhookQueueItem item)
    {
        if (!TryEnqueueResult)
        {
            Snapshot = Snapshot with
            {
                TotalDropped = Snapshot.TotalDropped + 1
            };
            return false;
        }

        _items.Add(item);
        Snapshot = Snapshot with
        {
            QueueDepth = Snapshot.QueueDepth + 1,
            TotalEnqueued = Snapshot.TotalEnqueued + 1
        };
        return true;
    }

    public async IAsyncEnumerable<WebhookQueueItem> DequeueAllAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        foreach (var item in _items)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Snapshot = Snapshot with
            {
                QueueDepth = Math.Max(0, Snapshot.QueueDepth - 1),
                TotalDequeued = Snapshot.TotalDequeued + 1
            };
            yield return item;
        }

        await Task.CompletedTask;
    }

    public WebhookQueueSnapshot GetSnapshot() => Snapshot;

    public void Complete()
    {
        CompleteCalls++;
    }
}

internal sealed class FakeConversationSummaryQueue : IConversationSummaryQueue
{
    private readonly List<ConversationSummaryWorkItem> _items = [];

    public bool TryEnqueueResult { get; set; } = true;
    public int CompleteCalls { get; private set; }
    public IReadOnlyList<ConversationSummaryWorkItem> Items => _items;
    public ConversationSummaryQueueSnapshot Snapshot { get; set; } = new(0, 64, 0, 0, 0);

    public bool TryEnqueue(ConversationSummaryWorkItem item)
    {
        if (!TryEnqueueResult)
        {
            Snapshot = Snapshot with
            {
                TotalDropped = Snapshot.TotalDropped + 1
            };
            return false;
        }

        _items.Add(item);
        Snapshot = Snapshot with
        {
            QueueDepth = Snapshot.QueueDepth + 1,
            TotalEnqueued = Snapshot.TotalEnqueued + 1
        };
        return true;
    }

    public async IAsyncEnumerable<ConversationSummaryWorkItem> DequeueAllAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        foreach (var item in _items)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Snapshot = Snapshot with
            {
                QueueDepth = Math.Max(0, Snapshot.QueueDepth - 1),
                TotalDequeued = Snapshot.TotalDequeued + 1
            };
            yield return item;
        }

        await Task.CompletedTask;
    }

    public ConversationSummaryQueueSnapshot GetSnapshot() => Snapshot;

    public void Complete()
    {
        CompleteCalls++;
    }
}

internal sealed class FakeEmbeddingService : IEmbeddingService
{
    public Func<string, CancellationToken, Task<IReadOnlyList<float>>> OnEmbedAsync { get; set; }
        = (text, ct) => Task.FromResult<IReadOnlyList<float>>([1f, 0f, 0f]);

    public Task<IReadOnlyList<float>> GetEmbeddingAsync(string text, CancellationToken ct = default)
        => OnEmbedAsync(text, ct);
}

internal sealed class FakeSemanticChunkSelector : ISemanticChunkSelector
{
    public int Calls { get; private set; }
    public Func<IReadOnlyList<DocumentChunk>, string, CancellationToken, Task<string>> OnSelectAsync { get; set; }
        = (chunks, prompt, ct) => Task.FromResult(string.Join("\n\n", chunks.Select(chunk => chunk.Text)));

    public Task<string> SelectRelevantTextAsync(IReadOnlyList<DocumentChunk> chunks, string userPrompt, CancellationToken ct = default)
    {
        Calls++;
        return OnSelectAsync(chunks, userPrompt, ct);
    }
}

internal sealed class FakeConversationSummaryGenerator : IConversationSummaryGenerator
{
    public int Calls { get; private set; }
    public Func<string?, IReadOnlyList<ConversationHistoryService.ChatMessage>, CancellationToken, Task<string>> OnGenerateAsync { get; set; }
        = (existingSummary, pendingMessages, ct) => Task.FromResult("summary");

    public Task<string> GenerateAsync(
        string? existingSummary,
        IReadOnlyList<ConversationHistoryService.ChatMessage> pendingMessages,
        CancellationToken ct = default)
    {
        Calls++;
        return OnGenerateAsync(existingSummary, pendingMessages, ct);
    }
}
internal sealed class StaticResultTextHandler(bool handled) : ITextMessageHandler
{
    public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
        => Task.FromResult(handled);
}

internal sealed class StaticResultImageHandler(bool handled) : IImageMessageHandler
{
    public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
        => Task.FromResult(handled);
}

internal sealed class StaticResultFileHandler(bool handled) : IFileMessageHandler
{
    public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
        => Task.FromResult(handled);
}

internal sealed class FakeWebhookMetrics : IWebhookMetrics
{
    public int WebhookRequests { get; private set; }
    public int InvalidSignatures { get; private set; }
    public int WebhookEvents { get; private set; }
    public int ThrottleRejected { get; private set; }
    public int AiBackoffRejected { get; private set; }
    public int AiTooManyRequests { get; private set; }
    public int AiQuotaExhausted { get; private set; }
    public int CacheHits { get; private set; }
    public int MergeJoined { get; private set; }
    public int QueueEnqueued { get; private set; }
    public int QueueDropped { get; private set; }
    public int QueueDequeued { get; private set; }
    public int RepliesSent { get; private set; }
    public int RepliesFailed { get; private set; }
    public Dictionary<string, int> MessageHandledByType { get; } = new(StringComparer.OrdinalIgnoreCase);

    public void RecordWebhookRequest() => WebhookRequests++;
    public void RecordInvalidSignature() => InvalidSignatures++;
    public void RecordWebhookEvents(int eventCount) => WebhookEvents += eventCount;

    public void RecordMessageHandled(string messageType, string? sourceType = null)
        => MessageHandledByType[messageType] = MessageHandledByType.GetValueOrDefault(messageType) + 1;

    public void RecordThrottleRejected(string handlerType, string messageType) => ThrottleRejected++;
    public void RecordAiBackoffRejected(string handlerType) => AiBackoffRejected++;
    public void RecordAiTooManyRequests(string handlerType) => AiTooManyRequests++;
    public void RecordAiQuotaExhausted(string handlerType) => AiQuotaExhausted++;
    public void RecordCacheHit(string handlerType) => CacheHits++;
    public void RecordMergeJoined(string handlerType) => MergeJoined++;
    public void RecordQueueEnqueued() => QueueEnqueued++;
    public void RecordQueueDropped() => QueueDropped++;
    public void RecordQueueDequeued() => QueueDequeued++;
    public void RecordReplySent(int messageCount) => RepliesSent++;
    public void RecordReplyFailed(int? statusCode = null) => RepliesFailed++;
}
internal sealed record CapturedLogEntry(
    LogLevel Level,
    string Message,
    Exception? Exception,
    IReadOnlyDictionary<string, object?> Properties);

internal sealed class TestLogger<T> : ILogger<T>
{
    private sealed class NullScope : IDisposable
    {
        public static readonly NullScope Instance = new();
        public void Dispose()
        {
        }
    }

    public List<CapturedLogEntry> Entries { get; } = [];

    public IDisposable BeginScope<TState>(TState state) where TState : notnull => NullScope.Instance;

    public bool IsEnabled(LogLevel logLevel) => true;

    public void Log<TState>(
        LogLevel logLevel,
        EventId eventId,
        TState state,
        Exception? exception,
        Func<TState, Exception?, string> formatter)
    {
        var properties = new Dictionary<string, object?>(StringComparer.Ordinal);
        if (state is IEnumerable<KeyValuePair<string, object?>> structuredState)
        {
            foreach (var pair in structuredState)
                properties[pair.Key] = pair.Value;
        }

        Entries.Add(new CapturedLogEntry(logLevel, formatter(state, exception), exception, properties));
    }
}

internal static class TestFactory
{
    public static IConfiguration BuildConfig(Dictionary<string, string?>? overrides = null)
    {
        var values = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
        {
            ["Line:ChannelAccessToken"] = "token",
            ["Line:ChannelSecret"] = "secret",
            ["App:TimeZoneId"] = "Asia/Taipei",
            ["App:UserThrottleSecondsText"] = "3",
            ["App:UserThrottleSecondsImage"] = "8",
            ["App:UserThrottleSecondsFile"] = "8",
            ["App:Ai429CooldownSeconds"] = "12",
            ["App:AiQuotaCooldownSeconds"] = "300",
            ["App:AiResponseCacheSeconds"] = "180",
            ["App:AiMergeWindowSeconds"] = "60",
            ["WebSearch:Enabled"] = "false",
            ["WebSearch:TavilyApiKey"] = ""
        };

        if (overrides is not null)
        {
            foreach (var pair in overrides)
                values[pair.Key] = pair.Value;
        }

        return new ConfigurationBuilder()
            .AddInMemoryCollection(values)
            .Build();
    }

    public static string BuildWebhookJson(LineEvent evt)
    {
        var body = new LineWebhookBody
        {
            Destination = "dest",
            Events = [evt]
        };

        return JsonSerializer.Serialize(body);
    }

    public static HttpContext CreateHttpContext(string body, string signature = "sig")
    {
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes(body));
        httpContext.Request.Headers["x-line-signature"] = signature;
        httpContext.Request.Scheme = "https";
        httpContext.Request.Host = new HostString("unit.test");
        return httpContext;
    }

    public static string? GetLastReplyText(RecordingHttpMessageHandler handler)
    {
        using var doc = GetLastReplyPayload(handler);
        if (doc is null)
            return null;

        return doc.RootElement.GetProperty("messages")[0].GetProperty("text").GetString();
    }

    public static JsonDocument? GetLastReplyPayload(RecordingHttpMessageHandler handler)
    {
        var replyRequest = handler.Requests.LastOrDefault(r => r.RequestUri?.ToString() == "https://api.line.me/v2/bot/message/reply");
        if (replyRequest?.Content is null)
            return null;

        var json = replyRequest.Content.ReadAsStringAsync().GetAwaiter().GetResult();
        return JsonDocument.Parse(json);
    }

    public static TextMessageHandler CreateTextHandler(
        IConfiguration config,
        IAiService ai,
        RecordingHttpMessageHandler httpHandler,
        IWebhookMetrics? metrics = null,
        UserRequestThrottleService? throttle = null,
        Ai429BackoffService? backoff = null,
        AiResponseCacheService? cache = null,
        InFlightRequestMergeService? merge = null,
        ILogger<TextMessageHandler>? logger = null,
        ILogger<LineReplyService>? replyLogger = null)
    {
        var actualMetrics = metrics ?? new FakeWebhookMetrics();
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config, actualMetrics, replyLogger ?? NullLogger<LineReplyService>.Instance);
        var webSearch = new WebSearchService(httpClient, config);
        var responder = new DateTimeIntentResponder(config);

        return new TextMessageHandler(
            config,
            ai,
            cache ?? new AiResponseCacheService(),
            merge ?? new InFlightRequestMergeService(),
            reply,
            webSearch,
            throttle ?? new UserRequestThrottleService(),
            backoff ?? new Ai429BackoffService(),
            responder,
            actualMetrics,
            logger ?? NullLogger<TextMessageHandler>.Instance);
    }

    public static ImageMessageHandler CreateImageHandler(
        IConfiguration config,
        IAiService ai,
        RecordingHttpMessageHandler httpHandler,
        IWebhookMetrics? metrics = null,
        UserRequestThrottleService? throttle = null,
        Ai429BackoffService? backoff = null,
        ILogger<ImageMessageHandler>? logger = null,
        ILogger<LineReplyService>? replyLogger = null)
    {
        var actualMetrics = metrics ?? new FakeWebhookMetrics();
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config, actualMetrics, replyLogger ?? NullLogger<LineReplyService>.Instance);
        var content = new LineContentService(httpClient, config);

        return new ImageMessageHandler(
            config,
            ai,
            reply,
            content,
            throttle ?? new UserRequestThrottleService(),
            backoff ?? new Ai429BackoffService(),
            actualMetrics,
            logger ?? NullLogger<ImageMessageHandler>.Instance);
    }

    public static FileMessageHandler CreateFileHandler(
        IConfiguration config,
        IAiService ai,
        RecordingHttpMessageHandler httpHandler,
        IWebhookMetrics? metrics = null,
        DocumentGroundingService? documents = null,
        GeneratedFileService? files = null,
        UserRequestThrottleService? throttle = null,
        Ai429BackoffService? backoff = null,
        ILogger<FileMessageHandler>? logger = null,
        ILogger<LineReplyService>? replyLogger = null)
    {
        var actualMetrics = metrics ?? new FakeWebhookMetrics();
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config, actualMetrics, replyLogger ?? NullLogger<LineReplyService>.Instance);
        var content = new LineContentService(httpClient, config);
        var actualDocuments = documents ?? new DocumentGroundingService(new DocumentChunker(), new DocumentChunkSelector());

        return new FileMessageHandler(
            config,
            ai,
            reply,
            content,
            actualDocuments,
            files ?? new GeneratedFileService(),
            throttle ?? new UserRequestThrottleService(),
            backoff ?? new Ai429BackoffService(),
            actualMetrics,
            logger ?? NullLogger<FileMessageHandler>.Instance);
    }

    public static LineWebhookDispatcher CreateDispatcher(
        IConfiguration config,
        RecordingHttpMessageHandler httpHandler,
        IWebhookMetrics? metrics,
        bool textHandled,
        bool imageHandled,
        bool fileHandled,
        ILogger<LineWebhookDispatcher>? logger = null,
        ILogger<LineReplyService>? replyLogger = null)
    {
        var actualMetrics = metrics ?? new FakeWebhookMetrics();
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config, actualMetrics, replyLogger ?? NullLogger<LineReplyService>.Instance);

        return new LineWebhookDispatcher(
            new StaticResultTextHandler(textHandled),
            new StaticResultImageHandler(imageHandled),
            new StaticResultFileHandler(fileHandled),
            reply,
            actualMetrics,
            logger ?? NullLogger<LineWebhookDispatcher>.Instance);
    }

    public static LineReplyService CreateReplyService(
        IConfiguration config,
        RecordingHttpMessageHandler httpHandler,
        IWebhookMetrics? metrics = null,
        ILogger<LineReplyService>? logger = null)
    {
        var actualMetrics = metrics ?? new FakeWebhookMetrics();
        return new LineReplyService(new HttpClient(httpHandler), config, actualMetrics, logger ?? NullLogger<LineReplyService>.Instance);
    }

    public static Task<string> InvokeMergedTextReplyAsync(TextMessageHandler handler, string userKey, string userText, CancellationToken ct = default)
    {
        return handler.GetMergedTextReplyAsync(userKey, userText, ct);
    }
}

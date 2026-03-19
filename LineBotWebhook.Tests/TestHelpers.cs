using System.Net;
using System.Reflection;
using System.Text;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
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

    public Func<string, string, CancellationToken, Task<string>> OnTextAsync { get; set; }
        = (msg, key, ct) => Task.FromResult("AI-OK");

    public Func<byte[], string, string, string, CancellationToken, Task<string>> OnImageAsync { get; set; }
        = (bytes, mime, prompt, key, ct) => Task.FromResult("IMG-OK");

    public Func<string, string, string, string, string, CancellationToken, Task<string>> OnFileAsync { get; set; }
        = (fileName, mime, text, prompt, key, ct) => Task.FromResult("FILE-OK");

    public Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default)
    {
        TextCalls++;
        return OnTextAsync(userMessage, userKey, ct);
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
}

internal sealed class FakeDispatcher : ILineWebhookDispatcher
{
    private readonly TaskCompletionSource<bool> _firstDispatchTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public int DispatchCalls { get; private set; }

    public Task DispatchAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        DispatchCalls++;
        _firstDispatchTcs.TrySetResult(true);
        return Task.CompletedTask;
    }

    public async Task<bool> WaitForDispatchAsync(TimeSpan timeout)
    {
        var completed = await Task.WhenAny(_firstDispatchTcs.Task, Task.Delay(timeout));
        return completed == _firstDispatchTcs.Task;
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
        var replyRequest = handler.Requests.LastOrDefault(r => r.RequestUri?.ToString() == "https://api.line.me/v2/bot/message/reply");
        if (replyRequest?.Content is null)
            return null;

        var json = replyRequest.Content.ReadAsStringAsync().GetAwaiter().GetResult();
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.GetProperty("messages")[0].GetProperty("text").GetString();
    }

    public static TextMessageHandler CreateTextHandler(
        IConfiguration config,
        IAiService ai,
        RecordingHttpMessageHandler httpHandler,
        UserRequestThrottleService? throttle = null,
        Ai429BackoffService? backoff = null,
        AiResponseCacheService? cache = null,
        InFlightRequestMergeService? merge = null)
    {
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config);
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
            NullLogger<TextMessageHandler>.Instance);
    }

    public static ImageMessageHandler CreateImageHandler(
        IConfiguration config,
        IAiService ai,
        RecordingHttpMessageHandler httpHandler,
        UserRequestThrottleService? throttle = null,
        Ai429BackoffService? backoff = null)
    {
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config);
        var content = new LineContentService(httpClient, config);

        return new ImageMessageHandler(
            config,
            ai,
            reply,
            content,
            throttle ?? new UserRequestThrottleService(),
            backoff ?? new Ai429BackoffService(),
            NullLogger<ImageMessageHandler>.Instance);
    }

    public static FileMessageHandler CreateFileHandler(
        IConfiguration config,
        IAiService ai,
        RecordingHttpMessageHandler httpHandler,
        GeneratedFileService? files = null,
        UserRequestThrottleService? throttle = null,
        Ai429BackoffService? backoff = null)
    {
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config);
        var content = new LineContentService(httpClient, config);

        return new FileMessageHandler(
            config,
            ai,
            reply,
            content,
            files ?? new GeneratedFileService(),
            throttle ?? new UserRequestThrottleService(),
            backoff ?? new Ai429BackoffService(),
            NullLogger<FileMessageHandler>.Instance);
    }

    public static LineWebhookDispatcher CreateDispatcher(
        IConfiguration config,
        RecordingHttpMessageHandler httpHandler,
        bool textHandled,
        bool imageHandled,
        bool fileHandled)
    {
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config);

        return new LineWebhookDispatcher(
            new StaticResultTextHandler(textHandled),
            new StaticResultImageHandler(imageHandled),
            new StaticResultFileHandler(fileHandled),
            reply);
    }

    public static Task<string> InvokeMergedTextReplyAsync(TextMessageHandler handler, string userKey, string userText, CancellationToken ct = default)
    {
        var method = typeof(TextMessageHandler).GetMethod("GetMergedTextReplyAsync", BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("GetMergedTextReplyAsync not found.");

        var task = method.Invoke(handler, [userKey, userText, ct]) as Task<string>;
        return task ?? throw new InvalidOperationException("GetMergedTextReplyAsync returned null.");
    }
}

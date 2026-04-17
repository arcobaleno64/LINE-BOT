using LineBotWebhook.Services;
using LineBotWebhook.Services.Documents;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.HttpOverrides;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.RateLimiting;

Environment.SetEnvironmentVariable("DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE", "false");
Environment.SetEnvironmentVariable("ASPNETCORE_HOSTBUILDER__RELOADCONFIGONCHANGE", "false");
Environment.SetEnvironmentVariable("DOTNET_USE_POLLING_FILE_WATCHER", "1");

var builder = WebApplication.CreateBuilder(args);

// ---------- DI: HttpClient ----------
builder.Services.AddHttpClient();

// ---------- DI: Persona Injection ----------
var personaFile = Path.Combine(builder.Environment.ContentRootPath, "persona_baymax.txt");
var defaultPersona = "你是國立科技大學副教授，同時主持多項資訊系統計畫。全程使用繁體中文，不自稱 AI。說話極度精簡，多數訊息僅一到兩句話，以提問推進而非直接下指令。";
var personaText = File.Exists(personaFile) ? File.ReadAllText(personaFile) : defaultPersona;
if (string.IsNullOrWhiteSpace(personaText))
{
    personaText = defaultPersona;
}
builder.Services.AddSingleton(new PersonaContext(personaText));

// ---------- DI: Conversation History ----------
builder.Services.AddSingleton<IConversationSummaryQueue, ConversationSummaryQueue>();
builder.Services.AddSingleton<IConversationSummaryGenerator, ConversationSummaryGenerator>();
builder.Services.AddSingleton<ConversationHistoryService>(sp =>
    new ConversationHistoryService(
        sp.GetRequiredService<IConversationSummaryQueue>(),
        sp.GetRequiredService<ILogger<ConversationHistoryService>>(),
        maxRounds: 15,
        idleMinutes: 480));
builder.Services.AddSingleton<IWebhookMetrics, WebhookMetrics>();
builder.Services.AddSingleton<IWebhookBackgroundQueue, WebhookBackgroundQueue>();
builder.Services.AddSingleton<IWebhookReadinessService, WebhookReadinessService>();
builder.Services.AddSingleton<IWebhookEventDeduplicationService, WebhookEventDeduplicationService>();

// ---------- DI: AI Service (主 provider + 自動 failover) ----------
builder.Services.AddSingleton<IAiService>(sp =>
    new FailoverAiService(
        sp.GetRequiredService<IHttpClientFactory>(),
        sp.GetRequiredService<IConfiguration>(),
        sp.GetRequiredService<ConversationHistoryService>(),
        sp.GetRequiredService<ILoggerFactory>(),
        sp.GetRequiredService<PersonaContext>(),
        sp.GetRequiredService<ILogger<FailoverAiService>>()));

// ---------- DI: LINE Reply Service ----------
builder.Services.AddSingleton<LineReplyService>(sp =>
    new LineReplyService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>(),
        sp.GetRequiredService<IWebhookMetrics>(),
        sp.GetRequiredService<ILogger<LineReplyService>>()));

// ---------- DI: LINE Content Service (下載圖片/檔案) ----------
builder.Services.AddSingleton<LineContentService>(sp =>
    new LineContentService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>()));

// ---------- DI: Loading Indicator ----------
builder.Services.AddSingleton<LoadingIndicatorService>(sp =>
    new LoadingIndicatorService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>(),
        sp.GetRequiredService<ILogger<LoadingIndicatorService>>()));

builder.Services.AddSingleton<GeneratedFileService>();
builder.Services.AddSingleton<DocumentChunker>();
builder.Services.AddSingleton<DocumentChunkSelector>();
builder.Services.AddSingleton<DocumentGroundingService>();
builder.Services.AddSingleton<IDocumentChunker, DocumentChunker>();
builder.Services.AddHttpClient<IEmbeddingService, GeminiEmbeddingService>();
builder.Services.AddSingleton<ISemanticChunkSelector, SemanticChunkSelector>();
builder.Services.AddSingleton<UserRequestThrottleService>();
builder.Services.AddSingleton<Ai429BackoffService>();
builder.Services.AddSingleton<AiResponseCacheService>();
builder.Services.AddSingleton<InFlightRequestMergeService>();
builder.Services.AddSingleton<IWebhookSignatureVerifier>(sp =>
    new WebhookSignatureVerifier(
        sp.GetRequiredService<IConfiguration>()["Line:ChannelSecret"]
        ?? throw new InvalidOperationException("Missing Line:ChannelSecret")));
builder.Services.AddSingleton<IPublicBaseUrlResolver, PublicBaseUrlResolver>();
builder.Services.AddSingleton<IDateTimeIntentResponder, DateTimeIntentResponder>();
builder.Services.AddSingleton<ITextMessageHandler, TextMessageHandler>();
builder.Services.AddSingleton<IImageMessageHandler, ImageMessageHandler>();
builder.Services.AddSingleton<IFileMessageHandler, FileMessageHandler>();
builder.Services.AddSingleton<ILineWebhookDispatcher, LineWebhookDispatcher>();
builder.Services.AddHostedService<WebhookBackgroundService>();
builder.Services.AddHostedService<ConversationSummaryWorker>();

builder.Services.AddSingleton<WebSearchService>(sp =>
    new WebSearchService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>()));

// ---------- MVC Controllers ----------
builder.Services.AddControllers();

// ---------- ForwardedHeaders (Render reverse proxy) ----------
builder.Services.Configure<ForwardedHeadersOptions>(options =>
{
    options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    options.KnownIPNetworks.Clear();
    options.KnownProxies.Clear(); // Trust all proxies — Render PaaS infrastructure
});

// ---------- Rate Limiting ----------
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;

    // Webhook: 200 requests/min per IP (generous for LINE Platform's multiple servers)
    options.AddPolicy("webhook-ip", httpContext =>
    {
        var ip = httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        return RateLimitPartition.GetFixedWindowLimiter(ip, _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = 200,
            Window = TimeSpan.FromMinutes(1),
            QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
            QueueLimit = 0
        });
    });

    // Downloads: 60 requests/min per IP
    options.AddPolicy("downloads-ip", httpContext =>
    {
        var ip = httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        return RateLimitPartition.GetFixedWindowLimiter(ip, _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = 60,
            Window = TimeSpan.FromMinutes(1),
            QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
            QueueLimit = 0
        });
    });
});

var app = builder.Build();
app.Lifetime.ApplicationStarted.Register(() =>
{
    app.Services.GetRequiredService<IWebhookReadinessService>().MarkStarted();
});

if (app.Environment.IsDevelopment())
{
    app.UseHttpsRedirection();
}

app.UseForwardedHeaders();
app.UseRateLimiter();

// ---------- Security: 驗證 App:PublicBaseUrl 已設定（避免 Host header injection）----------
var startupLogger = app.Services.GetRequiredService<ILogger<Program>>();
if (string.IsNullOrWhiteSpace(app.Configuration["App:PublicBaseUrl"]))
{
    startupLogger.LogWarning(
        "App:PublicBaseUrl is not configured. Download links will fall back to request Host header, " +
        "which is attacker-controlled. Set App:PublicBaseUrl in production to prevent host header injection.");
}

app.MapControllers();
app.MapGet("/", () => Results.Ok("LINE Bot Webhook is running"));
app.MapMethods("/", ["HEAD"], () => Results.Ok());
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));
app.MapMethods("/health", ["HEAD"], () => Results.Ok());
app.MapGet("/ready", (IWebhookReadinessService readiness) =>
{
    var snapshot = readiness.GetSnapshot();
    return Results.Json(snapshot, statusCode: snapshot.IsReady ? StatusCodes.Status200OK : StatusCodes.Status503ServiceUnavailable);
});

app.Run();

public partial class Program
{
}

using LineBotWebhook.Services;
using LineBotWebhook.Services.Documents;
using Microsoft.AspNetCore.Mvc;

Environment.SetEnvironmentVariable("DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE", "false");
Environment.SetEnvironmentVariable("ASPNETCORE_HOSTBUILDER__RELOADCONFIGONCHANGE", "false");
Environment.SetEnvironmentVariable("DOTNET_USE_POLLING_FILE_WATCHER", "1");

var builder = WebApplication.CreateBuilder(args);

// ---------- DI: HttpClient ----------
builder.Services.AddHttpClient();

// ---------- DI: Persona Injection ----------
var personaFile = Path.Combine(builder.Environment.ContentRootPath, "persona_baymax.txt");
var personaText = File.Exists(personaFile) ? File.ReadAllText(personaFile) : "你是一位親切的管家，語氣溫暖有禮、回答精簡實用，必要時可條列重點。請全程使用繁體中文，並避免自稱是 AI。";
builder.Services.AddSingleton(new PersonaContext(personaText));

// ---------- DI: Conversation History ----------
builder.Services.AddSingleton<IConversationSummaryQueue, ConversationSummaryQueue>();
builder.Services.AddSingleton<IConversationSummaryGenerator, ConversationSummaryGenerator>();
builder.Services.AddSingleton<ConversationHistoryService>(sp =>
    new ConversationHistoryService(
        sp.GetRequiredService<IConversationSummaryQueue>(),
        sp.GetRequiredService<ILogger<ConversationHistoryService>>(),
        maxRounds: 15,
        idleMinutes: -1));
builder.Services.AddSingleton<IWebhookMetrics, WebhookMetrics>();
builder.Services.AddSingleton<IWebhookBackgroundQueue, WebhookBackgroundQueue>();
builder.Services.AddSingleton<IWebhookReadinessService, WebhookReadinessService>();

// ---------- DI: AI Service (主 provider + 自動 failover) ----------
builder.Services.AddSingleton<IAiService>(sp =>
    new FailoverAiService(
        sp.GetRequiredService<IHttpClientFactory>(),
        sp.GetRequiredService<IConfiguration>(),
        sp.GetRequiredService<ConversationHistoryService>(),
        sp.GetRequiredService<ILoggerFactory>(),
        sp.GetRequiredService<PersonaContext>(),
        sp.GetRequiredService<ILoggerFactory>(),
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

var app = builder.Build();
app.Lifetime.ApplicationStarted.Register(() =>
{
    app.Services.GetRequiredService<IWebhookReadinessService>().MarkStarted();
});

if (app.Environment.IsDevelopment())
{
    app.UseHttpsRedirection();
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

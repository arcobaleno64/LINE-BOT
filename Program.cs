using LineBotWebhook.Services;

var builder = WebApplication.CreateBuilder(args);

// ---------- DI: HttpClient ----------
builder.Services.AddHttpClient();

// ---------- DI: Conversation History ----------
builder.Services.AddSingleton(new ConversationHistoryService(maxRounds: 15, idleMinutes: -1));

// ---------- DI: AI Service (依設定切換 Provider) ----------
var provider = builder.Configuration["Ai:Provider"] ?? "OpenAI";
switch (provider)
{
    case "Gemini":
        builder.Services.AddSingleton<IAiService>(sp =>
            new GeminiService(
                sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
                sp.GetRequiredService<IConfiguration>(),
                sp.GetRequiredService<ConversationHistoryService>()));
        break;

    case "Claude":
        builder.Services.AddSingleton<IAiService>(sp =>
            new ClaudeService(
                sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
                sp.GetRequiredService<IConfiguration>(),
                sp.GetRequiredService<ConversationHistoryService>()));
        break;

    case "OpenAI":
    default:
        builder.Services.AddSingleton<IAiService>(sp =>
            new OpenAiService(
                sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
                sp.GetRequiredService<IConfiguration>(),
                sp.GetRequiredService<ConversationHistoryService>()));
        break;
}

// ---------- DI: LINE Reply Service ----------
builder.Services.AddSingleton<LineReplyService>(sp =>
    new LineReplyService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>()));

// ---------- DI: LINE Content Service (下載圖片/檔案) ----------
builder.Services.AddSingleton<LineContentService>(sp =>
    new LineContentService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>()));

builder.Services.AddSingleton<GeneratedFileService>();
builder.Services.AddSingleton<UserRequestThrottleService>();
builder.Services.AddSingleton<Ai429BackoffService>();
builder.Services.AddSingleton<AiResponseCacheService>();
builder.Services.AddSingleton<InFlightRequestMergeService>();

builder.Services.AddSingleton<WebSearchService>(sp =>
    new WebSearchService(
        sp.GetRequiredService<IHttpClientFactory>().CreateClient(),
        sp.GetRequiredService<IConfiguration>()));

// ---------- MVC Controllers ----------
builder.Services.AddControllers();

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.UseHttpsRedirection();
}

app.MapControllers();
app.MapGet("/", () => Results.Ok("LINE Bot Webhook is running"));
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));

app.Run();

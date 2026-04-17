using System.Net.Http.Json;
using System.Text.Json;

namespace LineBotWebhook.Services;

public sealed class GeminiEmbeddingService(HttpClient http, IConfiguration config) : IEmbeddingService
{
    private readonly HttpClient _http = http;
    private readonly IConfiguration _config = config;

    public async Task<IReadOnlyList<float>> GetEmbeddingAsync(string text, CancellationToken ct = default)
    {
        var apiKey = _config["Ai:Gemini:ApiKey"]
            ?? throw new InvalidOperationException("Missing Ai:Gemini:ApiKey");
        var endpoint = (_config["Ai:Gemini:EmbeddingEndpoint"] ?? "https://generativelanguage.googleapis.com/v1beta/models").TrimEnd('/');
        var model = _config["Ai:Gemini:EmbeddingModel"] ?? "text-embedding-004";

        var payload = new
        {
            model = $"models/{model}",
            content = new
            {
                parts = new[]
                {
                    new
                    {
                        text = text.Length > 4000 ? text[..4000] : text
                    }
                }
            }
        };

        using var request = new HttpRequestMessage(HttpMethod.Post, $"{endpoint}/{model}:embedContent");
        request.Headers.Add("x-goog-api-key", apiKey);
        request.Content = JsonContent.Create(payload);
        using var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
        var values = doc.RootElement
            .GetProperty("embedding")
            .GetProperty("values")
            .EnumerateArray()
            .Select(value => value.GetSingle())
            .ToArray();

        if (values.Length == 0)
            throw new InvalidOperationException("Gemini embedding response did not contain values.");

        return values;
    }
}

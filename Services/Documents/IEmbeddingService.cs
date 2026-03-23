namespace LineBotWebhook.Services;

public interface IEmbeddingService
{
    Task<IReadOnlyList<float>> GetEmbeddingAsync(string text, CancellationToken ct = default);
}

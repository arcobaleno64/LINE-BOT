namespace LineBotWebhook.Services;

public class PublicBaseUrlResolver : IPublicBaseUrlResolver
{
    private readonly IConfiguration _config;

    public PublicBaseUrlResolver(IConfiguration config)
    {
        _config = config;
    }

    public string Resolve(HttpRequest request)
    {
        var configured = _config["App:PublicBaseUrl"];
        if (!string.IsNullOrWhiteSpace(configured))
            return configured.TrimEnd('/');

        var proto = request.Headers["x-forwarded-proto"].ToString();
        if (string.IsNullOrWhiteSpace(proto))
            proto = request.Scheme;

        return $"{proto}://{request.Host}".TrimEnd('/');
    }
}

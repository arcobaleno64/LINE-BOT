namespace LineBotWebhook.Services;

public interface IPublicBaseUrlResolver
{
    string Resolve(HttpRequest request);
}

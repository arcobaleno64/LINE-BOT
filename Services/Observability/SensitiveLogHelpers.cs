using System.Net;

namespace LineBotWebhook.Services;

internal static class SensitiveLogHelpers
{
    public static int? GetStatusCode(Exception ex)
    {
        if (ex is HttpRequestException httpEx && httpEx.StatusCode is HttpStatusCode statusCode)
            return (int)statusCode;

        return ex.InnerException is not null ? GetStatusCode(ex.InnerException) : null;
    }

    public static string GetFailureType(Exception ex) => ex.GetType().Name;
}

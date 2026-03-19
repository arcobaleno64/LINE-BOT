namespace LineBotWebhook.Services;

public interface IDateTimeIntentResponder
{
    bool TryBuildReply(string text, out string reply);
}

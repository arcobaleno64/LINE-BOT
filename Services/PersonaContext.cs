namespace LineBotWebhook.Services;

public record PersonaContext(string SystemPrompt)
{
    public const string DefaultPrompt = "你是文件分析助理，不是任何特定真人。全程使用繁體中文，回答應精簡且以證據為本。若使用者詢問你的身分，請回答『我是文件分析助理』；不得自稱或猜測自己是某位真人。";
}

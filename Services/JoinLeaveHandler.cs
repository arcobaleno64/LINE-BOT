using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public interface IJoinLeaveHandler
{
    Task<bool> HandleAsync(LineEvent evt, CancellationToken ct);
}

public class JoinLeaveHandler : IJoinLeaveHandler
{
    private readonly GroupRegistrationStore _store;
    private readonly LineReplyService _reply;
    private readonly IConfiguration _config;
    private readonly ILogger<JoinLeaveHandler> _logger;

    public JoinLeaveHandler(
        GroupRegistrationStore store,
        LineReplyService reply,
        IConfiguration config,
        ILogger<JoinLeaveHandler> logger)
    {
        _store = store;
        _reply = reply;
        _config = config;
        _logger = logger;
    }

    public async Task<bool> HandleAsync(LineEvent evt, CancellationToken ct)
    {
        if (evt.Type is not ("join" or "leave"))
            return false;

        var groupId = evt.Source?.GroupId;
        if (string.IsNullOrEmpty(groupId))
            return false;

        if (evt.Type == "join")
            return await HandleJoinAsync(evt, groupId, ct);

        return await HandleLeaveAsync(evt, groupId, ct);
    }

    private async Task<bool> HandleJoinAsync(LineEvent evt, string groupId, CancellationToken ct)
    {
        var inserted = await _store.UpsertJoinAsync(groupId, evt.Timestamp, evt.WebhookEventId, ct);
        if (!inserted)
            return true;

        if (!string.IsNullOrEmpty(evt.ReplyToken))
        {
            var botName = _config["App:BotDisplayName"] ?? "Bot";
            var welcome = $"大家好，我是 {botName}。\n" +
                          $"若要啟用推播通知，請輸入「@{botName} 啟用推播」。\n" +
                          $"輸入「@{botName} 說明」可查看所有指令。";
            try
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, welcome, ct);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogDebug(ex, "Failed to send welcome message. GroupId={GroupIdFingerprint}",
                    Fingerprint(groupId));
            }
        }

        return true;
    }

    private async Task<bool> HandleLeaveAsync(LineEvent evt, string groupId, CancellationToken ct)
    {
        await _store.UpsertLeaveAsync(groupId, evt.Timestamp, evt.WebhookEventId, ct);
        return true;
    }

    private static string Fingerprint(string id) => id.Length > 8 ? id[..4] + "…" + id[^4..] : "****";
}

namespace LineBotWebhook.Services;

/// <summary>Contains the neutral assistant prompt and an optional private-chat pilot prompt.</summary>
public sealed class PersonaContext
{
    private readonly HashSet<string> _privatePilotAdminUserIds;

    public const string DefaultPrompt = "你是文件分析助理，不是任何特定真人。全程使用繁體中文，回答應精簡且以證據為本。若使用者詢問你的身分，請回答『我是文件分析助理』；不得自稱或猜測自己是某位真人。";

    public PersonaContext(
        string systemPrompt,
        bool privatePersonaPilotEnabled = false,
        string? privatePersonaPilotPrompt = null,
        IEnumerable<string>? privatePilotAdminUserIds = null)
    {
        SystemPrompt = systemPrompt;
        PrivatePersonaPilotEnabled = privatePersonaPilotEnabled;
        PrivatePersonaPilotPrompt = privatePersonaPilotPrompt;
        _privatePilotAdminUserIds = privatePilotAdminUserIds?
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Select(id => id.Trim())
            .ToHashSet(StringComparer.Ordinal)
            ?? new HashSet<string>(StringComparer.Ordinal);
    }

    /// <summary>The default neutral prompt used by every conversation.</summary>
    public string SystemPrompt { get; }

    /// <summary>Whether the explicitly configured private-persona pilot is enabled.</summary>
    public bool PrivatePersonaPilotEnabled { get; }

    /// <summary>The de-identified pilot instructions, if configured.</summary>
    public string? PrivatePersonaPilotPrompt { get; }

    /// <summary>Creates persona settings from deployment configuration without logging identity or prompt values.</summary>
    public static PersonaContext FromConfiguration(IConfiguration configuration)
    {
        var adminIds = configuration["App:GroupAdminUserIds"]?
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var enabled = bool.TryParse(configuration["App:PrivatePersonaPilotEnabled"], out var parsedEnabled)
            && parsedEnabled;

        return new PersonaContext(
            DefaultPrompt,
            enabled,
            configuration["App:PrivatePersonaPilotPrompt"],
            adminIds);
    }

    /// <summary>Returns pilot instructions only for an explicitly enabled, allowlisted one-to-one text request.</summary>
    public string GetSystemPromptForRequest(string userKey, bool isPrivateTextRequest)
    {
        if (!isPrivateTextRequest
            || !PrivatePersonaPilotEnabled
            || string.IsNullOrWhiteSpace(PrivatePersonaPilotPrompt)
            || _privatePilotAdminUserIds.Count != 1)
        {
            return SystemPrompt;
        }

        var separatorIndex = userKey.IndexOf(':');
        if (separatorIndex <= 0
            || separatorIndex == userKey.Length - 1
            || userKey.IndexOf(':', separatorIndex + 1) >= 0)
        {
            return SystemPrompt;
        }

        var sourceId = userKey[..separatorIndex];
        var userId = userKey[(separatorIndex + 1)..];
        if (!string.Equals(sourceId, userId, StringComparison.Ordinal)
            || !_privatePilotAdminUserIds.Contains(userId))
        {
            return SystemPrompt;
        }

        return $"{SystemPrompt}\n\n{PrivatePersonaPilotPrompt.Trim()}";
    }
}

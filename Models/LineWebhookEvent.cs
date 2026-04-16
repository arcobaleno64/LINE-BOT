using System.Text.Json.Serialization;

namespace LineBotWebhook.Models;

/// <summary>LINE webhook 頂層結構</summary>
public class LineWebhookBody
{
    [JsonPropertyName("destination")]
    public string Destination { get; set; } = string.Empty;

    [JsonPropertyName("events")]
    public List<LineEvent> Events { get; set; } = [];
}

public class LineEvent
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    [JsonPropertyName("replyToken")]
    public string? ReplyToken { get; set; }

    [JsonPropertyName("source")]
    public LineSource? Source { get; set; }

    [JsonPropertyName("message")]
    public LineMessage? Message { get; set; }

    [JsonPropertyName("postback")]
    public LinePostback? Postback { get; set; }

    [JsonPropertyName("timestamp")]
    public long Timestamp { get; set; }

    [JsonPropertyName("webhookEventId")]
    public string WebhookEventId { get; set; } = string.Empty;
}

public class LineSource
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;   // "user" | "group" | "room"

    [JsonPropertyName("userId")]
    public string? UserId { get; set; }

    [JsonPropertyName("groupId")]
    public string? GroupId { get; set; }

    [JsonPropertyName("roomId")]
    public string? RoomId { get; set; }
}

public class LineMessage
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;   // "text", "image", ...

    [JsonPropertyName("text")]
    public string? Text { get; set; }

    [JsonPropertyName("fileName")]
    public string? FileName { get; set; }

    [JsonPropertyName("fileSize")]
    public long? FileSize { get; set; }

    [JsonPropertyName("mention")]
    public LineMention? Mention { get; set; }

    [JsonPropertyName("quoteToken")]
    public string? QuoteToken { get; set; }
}

public class LinePostback
{
    [JsonPropertyName("data")]
    public string Data { get; set; } = string.Empty;

    [JsonPropertyName("params")]
    public LinePostbackParams? Params { get; set; }
}

public class LinePostbackParams
{
    [JsonPropertyName("date")]
    public string? Date { get; set; }

    [JsonPropertyName("time")]
    public string? Time { get; set; }

    [JsonPropertyName("datetime")]
    public string? Datetime { get; set; }
}

public class LineMention
{
    [JsonPropertyName("mentionees")]
    public List<LineMentionee> Mentionees { get; set; } = [];
}

public class LineMentionee
{
    [JsonPropertyName("index")]
    public int Index { get; set; }

    [JsonPropertyName("length")]
    public int Length { get; set; }

    [JsonPropertyName("userId")]
    public string? UserId { get; set; }

    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    /// <summary>true 表示被 mention 的是本 Bot 自己</summary>
    [JsonPropertyName("isSelf")]
    public bool IsSelf { get; set; }
}

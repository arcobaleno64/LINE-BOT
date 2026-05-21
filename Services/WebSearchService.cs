using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace LineBotWebhook.Services;

public class WebSearchService
{
    public sealed record SearchSource(string Title, string Url, string Snippet);

    public sealed record SearchOutcome(
        bool Triggered,
        bool Succeeded,
        string Message,
        string ContextForAi,
        IReadOnlyList<SearchSource> Sources);

    private static readonly Regex WebIntentRegex = new(
        @"(上網|網路|google|搜尋|search|查資料|查一下|幫我查|幫我找|最新|即時|新聞|消息|資訊)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    // 限制單次搜尋回應之最大讀入長度，避免遠端服務回傳異常大型 payload 撐爆記憶體。
    private const long MaxResponseBytes = 2 * 1024 * 1024;

    private readonly HttpClient _http;
    private readonly bool _enabled;
    private readonly string _apiKey;
    private readonly string _endpoint;
    private readonly int _maxResults;

    public WebSearchService(HttpClient http, IConfiguration config)
    {
        _http = http;
        _enabled = !bool.TryParse(config["WebSearch:Enabled"], out var enabled) || enabled;
        _apiKey = config["WebSearch:TavilyApiKey"] ?? string.Empty;
        _endpoint = config["WebSearch:Endpoint"] ?? "https://api.tavily.com/search";
        _maxResults = int.TryParse(config["WebSearch:MaxResults"], out var parsed)
            ? Math.Clamp(parsed, 1, 8)
            : 4;
    }

    public bool ShouldTrigger(string userText)
    {
        if (string.IsNullOrWhiteSpace(userText))
            return false;

        var normalized = Normalize(userText);
        if (ContainsAny(normalized, "現在幾點", "幾月幾號", "星期幾", "禮拜幾", "週幾"))
            return false;

        var hasRecencyCue = ContainsAny(normalized, "最新", "即時", "今天新聞", "今日新聞", "最新消息", "最新資訊");
        var hasSearchCue = WebIntentRegex.IsMatch(normalized);
        return hasRecencyCue || hasSearchCue;
    }

    public async Task<SearchOutcome> TrySearchAsync(string query, CancellationToken ct = default)
    {
        if (!ShouldTrigger(query))
            return new SearchOutcome(false, false, string.Empty, string.Empty, []);

        if (!_enabled)
            return new SearchOutcome(true, false, "最新資料查詢功能目前未啟用。", string.Empty, []);

        if (string.IsNullOrWhiteSpace(_apiKey))
            return new SearchOutcome(true, false, "最新資料查詢尚未設定 API Key（WebSearch:TavilyApiKey）。", string.Empty, []);

        var payload = new
        {
            query,
            search_depth = "basic",
            max_results = _maxResults,
            include_answer = false,
            include_images = false
        };

        using var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", _apiKey);

        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
        if (!response.IsSuccessStatusCode)
            return new SearchOutcome(true, false, "目前無法連線到網路搜尋服務，請稍後再試。", string.Empty, []);

        if (response.Content.Headers.ContentLength is { } declaredLength && declaredLength > MaxResponseBytes)
            return new SearchOutcome(true, false, "查詢回應過大，已略過。", string.Empty, []);

        using var responseStream = await response.Content.ReadAsStreamAsync(ct);
        await using var boundedStream = new BoundedReadStream(responseStream, MaxResponseBytes);
        JsonDocument doc;
        try
        {
            doc = await JsonDocument.ParseAsync(boundedStream, cancellationToken: ct);
        }
        catch (InvalidOperationException)
        {
            // BoundedReadStream 超限時拋出 InvalidOperationException。
            return new SearchOutcome(true, false, "查詢回應過大，已略過。", string.Empty, []);
        }
        using var _doc = doc;
        if (!doc.RootElement.TryGetProperty("results", out var results) || results.ValueKind != JsonValueKind.Array)
            return new SearchOutcome(true, false, "查詢完成，但沒有取得可用的資料來源。", string.Empty, []);

        var sources = new List<SearchSource>();
        foreach (var item in results.EnumerateArray())
        {
            var title = item.TryGetProperty("title", out var t) ? (t.GetString() ?? "(未命名來源)") : "(未命名來源)";
            var url = item.TryGetProperty("url", out var u) ? (u.GetString() ?? string.Empty) : string.Empty;
            var content = item.TryGetProperty("content", out var c) ? (c.GetString() ?? string.Empty) : string.Empty;

            if (string.IsNullOrWhiteSpace(url) && string.IsNullOrWhiteSpace(content))
                continue;

            var snippet = content.Length > 600 ? content[..600] + "..." : content;
            sources.Add(new SearchSource(title.Trim(), url.Trim(), snippet.Trim()));
            if (sources.Count >= _maxResults)
                break;
        }

        if (sources.Count == 0)
            return new SearchOutcome(true, false, "查詢完成，但沒有找到足夠可信的資料來源。", string.Empty, []);

        var context = BuildContextForAi(sources);
        return new SearchOutcome(true, true, string.Empty, context, sources);
    }

    public static string BuildSourceList(IReadOnlyList<SearchSource> sources)
    {
        if (sources.Count == 0)
            return "(無)";

        var sb = new StringBuilder();
        for (var i = 0; i < sources.Count; i++)
        {
            sb.Append(i + 1).Append(". ").Append(sources[i].Title).Append('\n')
              .Append("   ").Append(sources[i].Url).Append('\n');
        }

        return sb.ToString().TrimEnd();
    }

    private static string BuildContextForAi(IReadOnlyList<SearchSource> sources)
    {
        var sb = new StringBuilder();
        sb.AppendLine("以下為網路搜尋結果摘要，可能含雜訊，請優先整合一致資訊：");
        sb.AppendLine();

        for (var i = 0; i < sources.Count; i++)
        {
            var s = sources[i];
            sb.AppendLine($"來源 {i + 1}：{s.Title}");
            if (!string.IsNullOrWhiteSpace(s.Url))
                sb.AppendLine($"網址：{s.Url}");
            if (!string.IsNullOrWhiteSpace(s.Snippet))
                sb.AppendLine($"摘要：{s.Snippet}");
            sb.AppendLine();
        }

        return sb.ToString().TrimEnd();
    }

    private static string Normalize(string text)
    {
        return text.Trim().ToLowerInvariant()
            .Replace("？", "")
            .Replace("?", "")
            .Replace("，", "")
            .Replace(",", "")
            .Replace("。", "")
            .Replace(" ", "");
    }

    private static bool ContainsAny(string text, params string[] keywords)
        => keywords.Any(k => text.Contains(k, StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// 包裝下游 Stream 並在累計讀取超過上限時拋出 InvalidOperationException，
    /// 用以阻擋遠端服務之異常巨大回應。
    /// </summary>
    private sealed class BoundedReadStream : Stream
    {
        private readonly Stream _inner;
        private readonly long _limit;
        private long _read;

        public BoundedReadStream(Stream inner, long limit)
        {
            _inner = inner;
            _limit = limit;
        }

        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position
        {
            get => _read;
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count)
        {
            var n = _inner.Read(buffer, offset, count);
            Advance(n);
            return n;
        }

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            var n = await _inner.ReadAsync(buffer, cancellationToken);
            Advance(n);
            return n;
        }

        public override async Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken)
        {
            var n = await _inner.ReadAsync(buffer.AsMemory(offset, count), cancellationToken);
            Advance(n);
            return n;
        }

        private void Advance(int n)
        {
            _read += n;
            if (_read > _limit)
                throw new InvalidOperationException("Bounded response stream exceeded byte limit.");
        }

        public override void Flush() => _inner.Flush();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        protected override void Dispose(bool disposing)
        {
            if (disposing)
                _inner.Dispose();
            base.Dispose(disposing);
        }
    }
}

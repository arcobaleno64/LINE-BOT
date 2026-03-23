using System.Net.Http.Headers;
using System.Text;
using UglyToad.PdfPig;
using UglyToad.PdfPig.Core;

namespace LineBotWebhook.Services;

public class LineContentService
{
    private const string ContentUrlBase = "https://api-data.line.me/v2/bot/message";
    private readonly HttpClient _http;
    private readonly string _accessToken;

    public LineContentService(HttpClient http, IConfiguration config)
    {
        _http = http;
        _accessToken = config["Line:ChannelAccessToken"]
            ?? throw new InvalidOperationException("Missing Line:ChannelAccessToken");
    }

    public async Task<(byte[] Data, string MimeType)> DownloadMessageContentAsync(string messageId, CancellationToken ct = default)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, $"{ContentUrlBase}/{messageId}/content");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        var bytes = await response.Content.ReadAsByteArrayAsync(ct);
        var mimeType = response.Content.Headers.ContentType?.MediaType ?? "application/octet-stream";

        return (bytes, mimeType);
    }

    public string ExtractTextFromFile(byte[] fileBytes, string fileName, string mimeType)
    {
        var extension = Path.GetExtension(fileName).ToLowerInvariant();
        var isPdf = mimeType.Equals("application/pdf", StringComparison.OrdinalIgnoreCase)
            || extension == ".pdf";

        if (isPdf)
            return ExtractTextFromPdf(fileBytes);

        var isLikelyText = mimeType.StartsWith("text/", StringComparison.OrdinalIgnoreCase)
            || extension is ".txt" or ".md" or ".csv" or ".json" or ".xml" or ".log";

        if (!isLikelyText)
        {
            throw new NotSupportedException("目前僅支援文字型檔案（txt/md/csv/json/xml/log）。");
        }

        return Encoding.UTF8.GetString(fileBytes);
    }

    private static string ExtractTextFromPdf(byte[] fileBytes)
    {
        try
        {
            using var stream = new MemoryStream(fileBytes);
            using var document = PdfDocument.Open(stream);

            var sb = new StringBuilder();
            foreach (var page in document.GetPages())
            {
                var text = page.Text;
                if (!string.IsNullOrWhiteSpace(text))
                {
                    if (sb.Length > 0)
                        sb.AppendLine().AppendLine();

                    sb.Append(text.Trim());
                }
            }

            var extracted = sb.ToString().Trim();
            if (string.IsNullOrWhiteSpace(extracted))
                throw new NotSupportedException("這份 PDF 似乎是掃描型或圖片型 PDF，目前先支援可直接擷取文字的 PDF。");

            return extracted;
        }
        catch (PdfDocumentFormatException ex)
        {
            throw new NotSupportedException("這份 PDF 似乎是掃描型或圖片型 PDF，目前先支援可直接擷取文字的 PDF。", ex);
        }
    }
}

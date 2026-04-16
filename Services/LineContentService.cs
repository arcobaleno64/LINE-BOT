using System.Net.Http.Headers;
using System.Text;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using DocumentFormat.OpenXml.Wordprocessing;
using UglyToad.PdfPig;
using UglyToad.PdfPig.Core;

namespace LineBotWebhook.Services;

public class LineContentService
{
    private const string ContentUrlBase = "https://api-data.line.me/v2/bot/message";
    private const int DefaultMaxFileSizeBytes = 10 * 1024 * 1024; // 10 MB

    private readonly HttpClient _http;
    private readonly string _accessToken;
    private readonly int _maxFileSizeBytes;

    public LineContentService(HttpClient http, IConfiguration config)
    {
        _http = http;
        _accessToken = config["Line:ChannelAccessToken"]
            ?? throw new InvalidOperationException("Missing Line:ChannelAccessToken");
        _maxFileSizeBytes = MessageHandlerHelpers.GetIntConfig(config, "App:MaxFileSizeBytes", DefaultMaxFileSizeBytes);
    }

    public async Task<(byte[] Data, string MimeType)> DownloadMessageContentAsync(string messageId, CancellationToken ct = default)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, $"{ContentUrlBase}/{messageId}/content");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        // ── 早期大小檢查：從 Content-Length header 快速拒絕 ──
        var contentLength = response.Content.Headers.ContentLength;
        if (contentLength.HasValue && contentLength.Value > _maxFileSizeBytes)
        {
            var limitMb = _maxFileSizeBytes / 1024 / 1024;
            throw new NotSupportedException($"檔案大小超過限制（上限 {limitMb} MB），無法處理。");
        }

        var bytes = await response.Content.ReadAsByteArrayAsync(ct);

        // ── 實際大小檢查（Header 可能不準時做最終確認）──
        if (bytes.Length > _maxFileSizeBytes)
        {
            var limitMb = _maxFileSizeBytes / 1024 / 1024;
            throw new NotSupportedException($"檔案大小超過限制（上限 {limitMb} MB），無法處理。");
        }

        var mimeType = response.Content.Headers.ContentType?.MediaType ?? "application/octet-stream";

        return (bytes, mimeType);
    }

    public string ExtractTextFromFile(byte[] fileBytes, string fileName, string mimeType)
    {
        var extension = Path.GetExtension(fileName).ToLowerInvariant();

        // ── PDF ──
        if (mimeType.Equals("application/pdf", StringComparison.OrdinalIgnoreCase) || extension == ".pdf")
            return ExtractTextFromPdf(fileBytes);

        // ── Office 文件 ──
        if (extension == ".docx" ||
            mimeType.Equals("application/vnd.openxmlformats-officedocument.wordprocessingml.document", StringComparison.OrdinalIgnoreCase))
            return ExtractTextFromDocx(fileBytes);

        if (extension == ".xlsx" ||
            mimeType.Equals("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", StringComparison.OrdinalIgnoreCase))
            return ExtractTextFromXlsx(fileBytes);

        if (extension == ".pptx" ||
            mimeType.Equals("application/vnd.openxmlformats-officedocument.presentationml.presentation", StringComparison.OrdinalIgnoreCase))
            return ExtractTextFromPptx(fileBytes);

        // ── 純文字（含編碼偵測）──
        var isLikelyText = mimeType.StartsWith("text/", StringComparison.OrdinalIgnoreCase)
            || extension is ".txt" or ".md" or ".csv" or ".json" or ".xml" or ".log";

        if (!isLikelyText)
            throw new NotSupportedException(
                "目前僅支援文字型檔案（txt/md/csv/json/xml/log）、PDF 文字型、Word（docx）、Excel（xlsx）、PowerPoint（pptx）。");

        return DecodeText(fileBytes);
    }

    // ── PDF ──────────────────────────────────────────────────────────

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

    // ── Office 文件 ──────────────────────────────────────────────────

    internal static string ExtractTextFromDocx(byte[] fileBytes)
    {
        try
        {
            using var stream = new MemoryStream(fileBytes);
            using var wordDoc = WordprocessingDocument.Open(stream, isEditable: false);

            var body = wordDoc.MainDocumentPart?.Document?.Body;
            if (body is null)
                throw new NotSupportedException("無法讀取 Word 文件內容。");

            var sb = new StringBuilder();
            foreach (var para in body.Descendants<Paragraph>())
            {
                var line = para.InnerText?.Trim();
                if (!string.IsNullOrEmpty(line))
                    sb.AppendLine(line);
            }

            var text = sb.ToString().Trim();
            if (string.IsNullOrWhiteSpace(text))
                throw new NotSupportedException("Word 文件未包含可擷取的文字內容。");

            return text;
        }
        catch (NotSupportedException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new NotSupportedException("Word 文件格式不支援或已損毀，無法解析。", ex);
        }
    }

    internal static string ExtractTextFromXlsx(byte[] fileBytes)
    {
        try
        {
            using var stream = new MemoryStream(fileBytes);
            using var spreadsheet = SpreadsheetDocument.Open(stream, isEditable: false);

            var workbookPart = spreadsheet.WorkbookPart;
            if (workbookPart is null)
                throw new NotSupportedException("無法讀取 Excel 文件內容。");

            // 建立 SharedStrings 查詢表
            var sharedStrings = workbookPart.SharedStringTablePart?.SharedStringTable
                .Elements<SharedStringItem>()
                .Select((item, index) => (index, item.InnerText))
                .ToDictionary(t => t.index, t => t.InnerText)
                ?? [];

            var sb = new StringBuilder();
            var sheetIndex = 0;
            foreach (var worksheetPart in workbookPart.WorksheetParts)
            {
                sheetIndex++;
                var sheet = workbookPart.Workbook.Descendants<Sheet>()
                    .ElementAtOrDefault(sheetIndex - 1);
                var sheetName = sheet?.Name?.Value ?? $"工作表{sheetIndex}";
                sb.AppendLine($"[{sheetName}]");

                var sheetData = worksheetPart.Worksheet.GetFirstChild<SheetData>();
                if (sheetData is null)
                    continue;

                foreach (var row in sheetData.Elements<Row>())
                {
                    var cells = row.Elements<Cell>()
                        .Select(cell => ResolveCellValue(cell, sharedStrings))
                        .Where(v => !string.IsNullOrWhiteSpace(v));
                    var rowText = string.Join("\t", cells);
                    if (!string.IsNullOrWhiteSpace(rowText))
                        sb.AppendLine(rowText);
                }

                sb.AppendLine();
            }

            var text = sb.ToString().Trim();
            if (string.IsNullOrWhiteSpace(text))
                throw new NotSupportedException("Excel 文件未包含可擷取的文字內容。");

            return text;
        }
        catch (NotSupportedException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new NotSupportedException("Excel 文件格式不支援或已損毀，無法解析。", ex);
        }
    }

    internal static string ResolveCellValue(Cell cell, Dictionary<int, string> sharedStrings)
    {
        var raw = cell.CellValue?.Text ?? string.Empty;
        if (cell.DataType?.Value == CellValues.SharedString
            && int.TryParse(raw, out var index)
            && sharedStrings.TryGetValue(index, out var shared))
            return shared;
        return raw;
    }

    internal static string ExtractTextFromPptx(byte[] fileBytes)
    {
        try
        {
            using var stream = new MemoryStream(fileBytes);
            using var presentation = PresentationDocument.Open(stream, isEditable: false);

            var presentationPart = presentation.PresentationPart;
            if (presentationPart is null)
                throw new NotSupportedException("無法讀取 PowerPoint 文件內容。");

            var sb = new StringBuilder();
            var slideIndex = 0;
            foreach (var slidePart in presentationPart.SlideParts)
            {
                slideIndex++;
                sb.AppendLine($"[第 {slideIndex} 頁]");
                var texts = slidePart.Slide.Descendants<DocumentFormat.OpenXml.Drawing.Text>()
                    .Select(t => t.Text?.Trim())
                    .Where(t => !string.IsNullOrWhiteSpace(t));
                foreach (var t in texts)
                    sb.AppendLine(t);
                sb.AppendLine();
            }

            var text = sb.ToString().Trim();
            if (string.IsNullOrWhiteSpace(text))
                throw new NotSupportedException("PowerPoint 文件未包含可擷取的文字內容。");

            return text;
        }
        catch (NotSupportedException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new NotSupportedException("PowerPoint 文件格式不支援或已損毀，無法解析。", ex);
        }
    }

    // ── 文字編碼偵測 ─────────────────────────────────────────────────

    /// <summary>
    /// 優先順序：BOM → UTF-8（嚴格模式） → GB18030（Big5 超集）→ Latin-1 fallback。
    /// </summary>
    internal static string DecodeText(byte[] bytes)
    {
        // 1. BOM 偵測
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
            return Encoding.UTF8.GetString(bytes, 3, bytes.Length - 3);
        if (bytes.Length >= 2 && bytes[0] == 0xFF && bytes[1] == 0xFE)
            return Encoding.Unicode.GetString(bytes, 2, bytes.Length - 2);
        if (bytes.Length >= 2 && bytes[0] == 0xFE && bytes[1] == 0xFF)
            return Encoding.BigEndianUnicode.GetString(bytes, 2, bytes.Length - 2);

        // 2. 嘗試嚴格 UTF-8
        try
        {
            return Encoding.UTF8.GetString(bytes); // UTF8 預設就是不含 BOM
        }
        catch (DecoderFallbackException)
        {
            // fall through
        }

        // 3. 嘗試 GB18030（Big5 超集，能解析繁體中文常見頁碼）
        try
        {
            var gb = Encoding.GetEncoding("GB18030",
                new EncoderExceptionFallback(),
                new DecoderExceptionFallback());
            return gb.GetString(bytes);
        }
        catch
        {
            // fall through
        }

        // 4. Latin-1 最終 fallback（不會丟例外）
        return Encoding.Latin1.GetString(bytes);
    }
}


using System.IO.Compression;
using System.Text;
using Microsoft.Extensions.Configuration;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

/// <summary>
/// Unit tests for LineContentService: encoding detection and Office file extraction.
/// </summary>
public class LineContentServiceTests
{
    // ── DecodeText ─────────────────────────────────────────────────

    [Fact]
    public void DecodeText_Utf8WithBom_StripsBoMAndDecodes()
    {
        var text = "BOM 測試文字";
        var bytes = Encoding.UTF8.GetPreamble().Concat(Encoding.UTF8.GetBytes(text)).ToArray();

        var result = LineContentService.DecodeText(bytes);

        Assert.Equal(text, result);
    }

    [Fact]
    public void DecodeText_PlainUtf8_Decodes()
    {
        var text = "Hello, 世界！";
        var bytes = Encoding.UTF8.GetBytes(text);

        var result = LineContentService.DecodeText(bytes);

        Assert.Equal(text, result);
    }

    [Fact]
    public void DecodeText_Utf16LeBom_Decodes()
    {
        var text = "UTF-16 LE 文字";
        var preamble = Encoding.Unicode.GetPreamble();
        var bytes = preamble.Concat(Encoding.Unicode.GetBytes(text)).ToArray();

        var result = LineContentService.DecodeText(bytes);

        Assert.Equal(text, result);
    }

    [Fact]
    public void DecodeText_Utf16BeBom_Decodes()
    {
        var text = "UTF-16 BE 文字";
        var preamble = Encoding.BigEndianUnicode.GetPreamble();
        var bytes = preamble.Concat(Encoding.BigEndianUnicode.GetBytes(text)).ToArray();

        var result = LineContentService.DecodeText(bytes);

        Assert.Equal(text, result);
    }

    [Fact]
    public void DecodeText_Latin1Fallback_DoesNotThrow()
    {
        // Pure Latin-1 bytes that are invalid in UTF-8 and GB18030
        var bytes = new byte[] { 0xE9, 0xE0, 0xFC }; // é à ü in Latin-1

        var result = LineContentService.DecodeText(bytes);

        Assert.False(string.IsNullOrEmpty(result));
    }

    // ── Office file extraction ──────────────────────────────────────

    [Fact]
    public void ExtractTextFromFile_Docx_ExtractsText()
    {
        var docxBytes = BuildMinimalDocx("Hello from Word 文件！");

        var result = LineContentService.ExtractTextFromDocx(docxBytes);

        Assert.Contains("Hello from Word 文件", result, StringComparison.Ordinal);
    }

    [Fact]
    public void ExtractTextFromFile_Xlsx_ExtractsText()
    {
        var xlsxBytes = BuildMinimalXlsx("工作表資料", "A1 值");

        var result = LineContentService.ExtractTextFromXlsx(xlsxBytes);

        Assert.Contains("A1 值", result, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("xl/sharedStrings.xml")]
    [InlineData("xl/workbook.xml")]
    [InlineData("xl/worksheets/sheet1.xml")]
    public void ExtractTextFromXlsx_MissingRequiredRoot_RejectsDocumentSafely(string partName)
    {
        var xlsxBytes = ReplaceZipEntry(BuildMinimalXlsx("工作表資料", "A1 值"), partName, "<broken/>");

        var ex = Assert.Throws<NotSupportedException>(() => LineContentService.ExtractTextFromXlsx(xlsxBytes));

        Assert.Contains("Excel", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ExtractTextFromFile_Pptx_ExtractsSlideText()
    {
        var service = new LineContentService(new HttpClient(), TestFactory.BuildConfig());
        var pptxBytes = BuildMinimalPptx("投影片文字抽取測試");

        var result = service.ExtractTextFromFile(
            pptxBytes,
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation");

        Assert.Contains("投影片文字抽取測試", result, StringComparison.Ordinal);
    }

    [Fact]
    public void ExtractTextFromPptx_MissingSlideRoot_RejectsDocumentSafely()
    {
        var pptxBytes = ReplaceZipEntry(BuildMinimalPptx("投影片文字"), "ppt/slides/slide1.xml", "<broken/>");

        var ex = Assert.Throws<NotSupportedException>(() => LineContentService.ExtractTextFromPptx(pptxBytes));

        Assert.Contains("PowerPoint", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ExtractTextFromFile_UnsupportedExtension_Throws()
    {
        var cfg = new Microsoft.Extensions.Configuration.ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Line:ChannelAccessToken"] = "fake-token"
            })
            .Build();
        var svc = new LineContentService(new HttpClient(), cfg);

        var ex = Assert.Throws<NotSupportedException>(() =>
            svc.ExtractTextFromFile([0x00], "binary.exe", "application/octet-stream"));

        Assert.Contains("支援", ex.Message, StringComparison.Ordinal);
    }

    // ── Helpers ────────────────────────────────────────────────────

    /// <summary>
    /// Very minimal valid .docx — just enough to pass through WordprocessingDocument.Open
    /// and expose paragraph text.
    /// </summary>
    private static byte[] BuildMinimalDocx(string paragraphText)
    {
        using var ms = new MemoryStream();
        using (var zip = new ZipArchive(ms, ZipArchiveMode.Create, leaveOpen: true))
        {
            // [Content_Types].xml
            AddEntry(zip, "[Content_Types].xml", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
""");

            // _rels/.rels
            AddEntry(zip, "_rels/.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
""");

            // word/_rels/document.xml.rels
            AddEntry(zip, "word/_rels/document.xml.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>
""");

            // word/document.xml
            AddEntry(zip, "word/document.xml", $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r>
        <w:t>{System.Security.SecurityElement.Escape(paragraphText)}</w:t>
      </w:r>
    </w:p>
  </w:body>
</w:document>
""");
        }
        return ms.ToArray();
    }

    /// <summary>Minimal valid .xlsx with one sheet and one string cell.</summary>
    private static byte[] BuildMinimalXlsx(string sheetName, string cellValue)
    {
        using var ms = new MemoryStream();
        using (var zip = new ZipArchive(ms, ZipArchiveMode.Create, leaveOpen: true))
        {
            AddEntry(zip, "[Content_Types].xml", $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
""");

            AddEntry(zip, "_rels/.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>
""");

            AddEntry(zip, "xl/_rels/workbook.xml.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    Target="sharedStrings.xml"/>
</Relationships>
""");

            AddEntry(zip, "xl/workbook.xml", $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{System.Security.SecurityElement.Escape(sheetName)}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
""");

            AddEntry(zip, "xl/sharedStrings.xml", $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">
  <si><t>{System.Security.SecurityElement.Escape(cellValue)}</t></si>
</sst>
""");

            AddEntry(zip, "xl/worksheets/sheet1.xml", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
    </row>
  </sheetData>
</worksheet>
""");
        }
        return ms.ToArray();
    }

    /// <summary>Minimal valid .pptx with one slide and one text shape.</summary>
    private static byte[] BuildMinimalPptx(string slideText)
    {
        using var ms = new MemoryStream();
        using (var zip = new ZipArchive(ms, ZipArchiveMode.Create, leaveOpen: true))
        {
            AddEntry(zip, "[Content_Types].xml", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
""");

            AddEntry(zip, "_rels/.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>
""");

            AddEntry(zip, "ppt/_rels/presentation.xml.rels", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
""");

            AddEntry(zip, "ppt/presentation.xml", """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>
</p:presentation>
""");

            AddEntry(zip, "ppt/slides/slide1.xml", $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Text Box 1"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
        <p:spPr/>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="zh-TW"/><a:t>{System.Security.SecurityElement.Escape(slideText)}</a:t></a:r></a:p></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
""");
        }
        return ms.ToArray();
    }

    private static byte[] ReplaceZipEntry(byte[] archiveBytes, string entryName, string replacementContent)
    {
        using var input = new MemoryStream(archiveBytes);
        using var output = new MemoryStream();
        using (var source = new ZipArchive(input, ZipArchiveMode.Read, leaveOpen: true))
        using (var target = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: true))
        {
            foreach (var sourceEntry in source.Entries)
            {
                var targetEntry = target.CreateEntry(sourceEntry.FullName);
                using var targetStream = targetEntry.Open();
                if (string.Equals(sourceEntry.FullName, entryName, StringComparison.Ordinal))
                {
                    using var writer = new StreamWriter(targetStream, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
                    writer.Write(replacementContent);
                }
                else
                {
                    using var sourceStream = sourceEntry.Open();
                    sourceStream.CopyTo(targetStream);
                }
            }
        }

        return output.ToArray();
    }

    private static void AddEntry(ZipArchive zip, string path, string content)
    {
        var entry = zip.CreateEntry(path);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        writer.Write(content);
    }
}

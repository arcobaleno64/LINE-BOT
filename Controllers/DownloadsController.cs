using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("downloads")]
public class DownloadsController(GeneratedFileService files) : ControllerBase
{
    private readonly GeneratedFileService _files = files;

    [HttpGet("{token}")]
    public IActionResult Get(string token)
    {
        var file = _files.Get(token);
        if (file is null || !System.IO.File.Exists(file.FilePath))
            return NotFound();

        var stream = System.IO.File.OpenRead(file.FilePath);
        return File(stream, file.ContentType, file.DownloadFileName);
    }
}

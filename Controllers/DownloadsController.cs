using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("downloads")]
[EnableRateLimiting("downloads-ip")]
public class DownloadsController(GeneratedFileService files) : ControllerBase
{
    private readonly GeneratedFileService _files = files;

    [HttpGet("{token}")]
    public IActionResult Get(string token)
    {
        var file = _files.Get(token);
        if (file is null || !System.IO.File.Exists(file.FilePath))
            return NotFound();

        return PhysicalFile(file.FilePath, file.ContentType, file.DownloadFileName);
    }
}

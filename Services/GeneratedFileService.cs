using System.Collections.Concurrent;
using System.Text;

namespace LineBotWebhook.Services;

public class GeneratedFileService
{
    public sealed record GeneratedFile(string FilePath, string DownloadFileName, string ContentType, DateTime CreatedAtUtc);

    private static readonly TimeSpan Retention = TimeSpan.FromHours(24);
    private readonly string _rootPath;
    private readonly ConcurrentDictionary<string, GeneratedFile> _files = new();

    public GeneratedFileService()
    {
        _rootPath = Path.Combine(AppContext.BaseDirectory, "generated-files");
        Directory.CreateDirectory(_rootPath);
    }

    public string SaveTextFile(string suggestedFileName, string content, string contentType = "text/markdown; charset=utf-8")
    {
        PruneExpired();

        var token = Guid.NewGuid().ToString("N");
        var safeName = MakeSafeFileName(suggestedFileName);
        var filePath = Path.Combine(_rootPath, $"{token}-{safeName}");
        File.WriteAllText(filePath, content, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        _files[token] = new GeneratedFile(filePath, safeName, contentType, DateTime.UtcNow);
        return token;
    }

    public GeneratedFile? Get(string token)
    {
        PruneExpired();
        return _files.TryGetValue(token, out var file) ? file : null;
    }

    private void PruneExpired()
    {
        var cutoff = DateTime.UtcNow - Retention;
        foreach (var entry in _files)
        {
            if (entry.Value.CreatedAtUtc >= cutoff)
                continue;

            _files.TryRemove(entry.Key, out var removed);
            if (removed is not null && File.Exists(removed.FilePath))
                File.Delete(removed.FilePath);
        }
    }

    private static string MakeSafeFileName(string fileName)
    {
        var invalidChars = Path.GetInvalidFileNameChars();
        var cleaned = new string(fileName.Select(ch => invalidChars.Contains(ch) ? '_' : ch).ToArray());
        return string.IsNullOrWhiteSpace(cleaned) ? "output.md" : cleaned;
    }
}

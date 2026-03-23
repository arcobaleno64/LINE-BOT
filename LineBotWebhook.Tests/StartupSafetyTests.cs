using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Configuration;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class StartupSafetyTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly WebApplicationFactory<Program> _factory;

    public StartupSafetyTests(WebApplicationFactory<Program> factory)
    {
        _factory = factory;
    }

    [Fact]
    public void RequiredDocumentServices_CanResolve()
    {
        var app = _factory.WithWebHostBuilder(builder =>
        {
            builder.ConfigureAppConfiguration((_, config) =>
            {
                config.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Ai:Provider"] = "Gemini",
                    ["Ai:Gemini:ApiKey"] = "test-gemini-key"
                });
            });
        });

        using var scope = app.Services.CreateScope();

        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IEmbeddingService>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<ISemanticChunkSelector>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IFileMessageHandler>());
    }
}

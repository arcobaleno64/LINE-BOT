using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
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
        using var scope = _factory.Services.CreateScope();

        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IEmbeddingService>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<ISemanticChunkSelector>());
        Assert.NotNull(scope.ServiceProvider.GetRequiredService<IFileMessageHandler>());
    }
}

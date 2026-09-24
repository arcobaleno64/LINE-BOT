using System.Net;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class HeadEndpointCompatibilityTests : IClassFixture<HeadEndpointCompatibilityTests.TestAppFactory>
{
    private readonly HttpClient _client;
    private readonly TestAppFactory _factory;

    public HeadEndpointCompatibilityTests(TestAppFactory factory)
    {
        _factory = factory;
        _client = factory.CreateClient(new WebApplicationFactoryClientOptions
        {
            AllowAutoRedirect = false
        });
    }

    [Fact]
    public void ProductionStartup_UsesNeutralAssistantIdentity()
    {
        var persona = _factory.Services.GetRequiredService<PersonaContext>();
        Assert.Equal(PersonaContext.DefaultPrompt, persona.SystemPrompt);
        Assert.DoesNotContain("教授", persona.SystemPrompt, StringComparison.Ordinal);
    }

    [Fact]
    public async Task GetRoot_ReturnsSuccess_AndUnchangedBody()
    {
        using var response = await _client.GetAsync("/");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("\"LINE Bot Webhook is running\"", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task GetHealth_ReturnsSuccess_AndUnchangedBody()
    {
        using var response = await _client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("\"status\":\"ok\"", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task HeadRoot_Returns200()
    {
        using var response = await _client.SendAsync(new HttpRequestMessage(HttpMethod.Head, "/"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task HeadHealth_Returns200()
    {
        using var response = await _client.SendAsync(new HttpRequestMessage(HttpMethod.Head, "/health"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    public sealed class TestAppFactory : WebApplicationFactory<Program>
    {
        protected override void ConfigureWebHost(Microsoft.AspNetCore.Hosting.IWebHostBuilder builder)
        {
            builder.UseEnvironment("Production");
            builder.ConfigureAppConfiguration((context, configBuilder) =>
            {
                configBuilder.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Line:ChannelAccessToken"] = "test-token",
                    ["Line:ChannelSecret"] = "test-secret",
                    ["Ai:OpenAI:ApiKey"] = "test-openai-key"
                });
            });
        }
    }
}

using LineBotWebhook.Services;
using Microsoft.Extensions.Configuration;
using Npgsql;

namespace LineBotWebhook.Tests;

public class PostgresConversationHistoryStoreTests
{
    [Fact]
    public void ResolveConnectionString_ParsesRenderPostgresUrlAndRequiresTls()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["DATABASE_URL"] = "postgresql://app%40name:p%40ss%3Aword@db.example:5544/linebot?sslmode=require"
            })
            .Build();

        var connectionString = PostgresConversationHistoryStore.ResolveConnectionString(configuration);

        var parsed = new NpgsqlConnectionStringBuilder(connectionString);
        Assert.Equal("db.example", parsed.Host);
        Assert.Equal(5544, parsed.Port);
        Assert.Equal("linebot", parsed.Database);
        Assert.Equal("app@name", parsed.Username);
        Assert.Equal("p@ss:word", parsed.Password);
        Assert.Equal(SslMode.Require, parsed.SslMode);
    }

    [Fact]
    public void ResolveConnectionString_PrefersExplicitConnectionString()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:Postgres"] = "Host=localhost;Database=linebot;Username=app;Password=test",
                ["DATABASE_URL"] = "postgresql://other:secret@db.example/other"
            })
            .Build();

        var connectionString = PostgresConversationHistoryStore.ResolveConnectionString(configuration);

        Assert.Equal("localhost", new NpgsqlConnectionStringBuilder(connectionString).Host);
    }
}

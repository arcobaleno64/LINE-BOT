using System.Net;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class GroupRegistrationStoreTests : IDisposable
{
    private readonly string _dbPath;
    private readonly GroupRegistrationStore _store;

    public GroupRegistrationStoreTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"test_groups_{Guid.NewGuid():N}.db");
        _store = new GroupRegistrationStore(_dbPath, NullLogger<GroupRegistrationStore>.Instance);
    }

    public void Dispose()
    {
        _store.Dispose();
        try { if (File.Exists(_dbPath)) File.Delete(_dbPath); } catch { }
    }

    [Fact]
    public async Task JoinCreatesActiveRecord()
    {
        var gid = "C" + new string('a', 32);
        var inserted = await _store.UpsertJoinAsync(gid, 1000, "evt1");
        Assert.True(inserted);

        var reg = await _store.GetAsync(gid);
        Assert.NotNull(reg);
        Assert.True(reg.Active);
        Assert.False(reg.PushEnabled);
    }

    [Fact]
    public async Task LeaveTombstonesAndDisablesPush()
    {
        var gid = "C" + new string('b', 32);
        await _store.UpsertJoinAsync(gid, 1000, "evt1");
        await _store.SetPushEnabledAsync(gid, true);

        await _store.UpsertLeaveAsync(gid, 2000, "evt2");

        var reg = await _store.GetAsync(gid);
        Assert.NotNull(reg);
        Assert.False(reg.Active);
        Assert.False(reg.PushEnabled);
        Assert.NotNull(reg.LeftAt);
    }

    [Fact]
    public async Task StaleJoinEventIsIgnored()
    {
        var gid = "C" + new string('c', 32);
        await _store.UpsertJoinAsync(gid, 2000, "evt2");
        var stale = await _store.UpsertJoinAsync(gid, 1000, "evt1");
        Assert.False(stale);
    }

    [Fact]
    public async Task DuplicateWebhookEventIdIsIgnored()
    {
        var gid = "C" + new string('d', 32);
        await _store.UpsertJoinAsync(gid, 1000, "evt1");
        var dup = await _store.UpsertJoinAsync(gid, 1000, "evt1");
        Assert.False(dup);
    }

    [Fact]
    public async Task RejoinAfterLeaveResetsActiveButNotPushEnabled()
    {
        var gid = "C" + new string('e', 32);
        await _store.UpsertJoinAsync(gid, 1000, "evt1");
        await _store.SetPushEnabledAsync(gid, true);
        await _store.UpsertLeaveAsync(gid, 2000, "evt2");
        await _store.UpsertJoinAsync(gid, 3000, "evt3");

        var reg = await _store.GetAsync(gid);
        Assert.NotNull(reg);
        Assert.True(reg.Active);
        Assert.False(reg.PushEnabled);
    }

    [Fact]
    public async Task SetPushEnabledOnInactiveGroupReturnsFalse()
    {
        var gid = "C" + new string('f', 32);
        await _store.UpsertJoinAsync(gid, 1000, "evt1");
        await _store.UpsertLeaveAsync(gid, 2000, "evt2");

        var result = await _store.SetPushEnabledAsync(gid, true);
        Assert.False(result);
    }

    [Fact]
    public async Task GetPushableGroupsReturnsOnlyActiveAndEnabled()
    {
        var g1 = "C" + new string('1', 32);
        var g2 = "C" + new string('2', 32);
        var g3 = "C" + new string('3', 32);

        await _store.UpsertJoinAsync(g1, 1000, "e1");
        await _store.SetPushEnabledAsync(g1, true);

        await _store.UpsertJoinAsync(g2, 1000, "e2");
        // g2: active but pushEnabled=false

        await _store.UpsertJoinAsync(g3, 1000, "e3");
        await _store.SetPushEnabledAsync(g3, true);
        await _store.UpsertLeaveAsync(g3, 2000, "e4");
        // g3: pushEnabled was true but leave disabled it

        var pushable = await _store.GetPushableGroupsAsync();
        Assert.Single(pushable);
        Assert.Equal(g1, pushable[0].GroupId);
    }

    [Fact]
    public async Task LeaveJoinOutOfOrderHandledByTimestamp()
    {
        var gid = "C" + new string('7', 32);
        await _store.UpsertLeaveAsync(gid, 2000, "evt_leave");
        var staleJoin = await _store.UpsertJoinAsync(gid, 1000, "evt_join");
        Assert.False(staleJoin);

        var reg = await _store.GetAsync(gid);
        Assert.NotNull(reg);
        Assert.False(reg.Active);
    }
}

public class LinePushServiceValidationTests
{
    [Theory]
    [InlineData("C0123456789abcdef0123456789abcdef", true)]
    [InlineData("Cabcdefabcdefabcdefabcdefabcdefab", true)]
    [InlineData("U0123456789abcdef0123456789abcdef", false)]
    [InlineData("R0123456789abcdef0123456789abcdef", false)]
    [InlineData("C0123", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    [InlineData("C0123456789ABCDEF0123456789ABCDEF", false)]
    public void IsValidGroupId(string? input, bool expected)
    {
        Assert.Equal(expected, LinePushService.IsValidGroupId(input));
    }
}

public class LinePushServiceTests : IDisposable
{
    private readonly string _dbPath;
    private readonly GroupRegistrationStore _store;
    private static readonly string TestGroupId = "C" + new string('a', 32);

    public LinePushServiceTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"push_test_{Guid.NewGuid():N}.db");
        _store = new GroupRegistrationStore(_dbPath, NullLogger<GroupRegistrationStore>.Instance);
    }

    public void Dispose()
    {
        _store.Dispose();
        try { if (File.Exists(_dbPath)) File.Delete(_dbPath); } catch { }
    }

    private LinePushService CreateService(RecordingHttpMessageHandler handler, int budget = 180)
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Line:ChannelAccessToken"] = "fake-token",
                ["App:PushMonthlyBudget"] = budget.ToString()
            }).Build();

        return new LinePushService(
            new HttpClient(handler), config, _store,
            new FakeWebhookMetrics(), NullLogger<LinePushService>.Instance);
    }

    [Fact]
    public async Task PushToUnknownGroupReturnsTargetNotFound()
    {
        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync(TestGroupId, "hello");
        Assert.Equal(PushResult.TargetNotFound, result);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task PushToActiveEnabledGroupAccepted()
    {
        await _store.UpsertJoinAsync(TestGroupId, 1000, "evt1");
        await _store.SetPushEnabledAsync(TestGroupId, true);

        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync(TestGroupId, "hello");
        Assert.Equal(PushResult.Accepted, result);
        Assert.Single(handler.Requests);

        var req = handler.Requests[0];
        Assert.Equal("https://api.line.me/v2/bot/message/push", req.RequestUri!.ToString());
        Assert.NotNull(req.Headers.GetValues("X-Line-Retry-Key").FirstOrDefault());
    }

    [Fact]
    public async Task PushAfterLeaveReturnsTargetNotFound()
    {
        await _store.UpsertJoinAsync(TestGroupId, 1000, "evt1");
        await _store.SetPushEnabledAsync(TestGroupId, true);
        await _store.UpsertLeaveAsync(TestGroupId, 2000, "evt2");

        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync(TestGroupId, "hello");
        Assert.Equal(PushResult.TargetNotFound, result);
    }

    [Fact]
    public async Task Push409ConflictReturnedAsConflict()
    {
        await _store.UpsertJoinAsync(TestGroupId, 1000, "evt1");
        await _store.SetPushEnabledAsync(TestGroupId, true);

        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.Conflict)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync(TestGroupId, "hello");
        Assert.Equal(PushResult.Conflict, result);
    }

    [Fact]
    public async Task Push403AutoDisablesPushEnabled()
    {
        await _store.UpsertJoinAsync(TestGroupId, 1000, "evt1");
        await _store.SetPushEnabledAsync(TestGroupId, true);

        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.Forbidden)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync(TestGroupId, "hello");
        Assert.Equal(PushResult.Rejected, result);

        var reg = await _store.GetAsync(TestGroupId);
        Assert.NotNull(reg);
        Assert.False(reg.PushEnabled);
    }

    [Fact]
    public async Task Push429ReturnsRateLimited()
    {
        await _store.UpsertJoinAsync(TestGroupId, 1000, "evt1");
        await _store.SetPushEnabledAsync(TestGroupId, true);

        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.TooManyRequests)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync(TestGroupId, "hello");
        Assert.Equal(PushResult.RateLimited, result);
    }

    [Fact]
    public async Task InvalidGroupIdReturnsRejected()
    {
        var handler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = CreateService(handler);

        var result = await service.PushTextAsync("U" + new string('a', 32), "hello");
        Assert.Equal(PushResult.Rejected, result);
    }
}

public class JoinLeaveHandlerTests : IDisposable
{
    private readonly string _dbPath;
    private readonly GroupRegistrationStore _store;
    private static readonly string TestGroupId = "C" + new string('a', 32);

    public JoinLeaveHandlerTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"jl_test_{Guid.NewGuid():N}.db");
        _store = new GroupRegistrationStore(_dbPath, NullLogger<GroupRegistrationStore>.Instance);
    }

    public void Dispose()
    {
        _store.Dispose();
        try { if (File.Exists(_dbPath)) File.Delete(_dbPath); } catch { }
    }

    private static IConfiguration BuildConfig(string botName = "TestBot") =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Line:ChannelAccessToken"] = "fake-token",
                ["App:BotDisplayName"] = botName
            }).Build();

    [Fact]
    public async Task JoinEventCreatesRegistrationAndSendsWelcome()
    {
        var config = BuildConfig();
        var httpHandler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var reply = TestFactory.CreateReplyService(config, httpHandler);
        var handler = new JoinLeaveHandler(_store, reply, config, NullLogger<JoinLeaveHandler>.Instance);

        var evt = new LineEvent
        {
            Type = "join",
            ReplyToken = "rt1",
            Source = new LineSource { Type = "group", GroupId = TestGroupId },
            Timestamp = 1000,
            WebhookEventId = "evt1"
        };

        var result = await handler.HandleAsync(evt, CancellationToken.None);
        Assert.True(result);

        var reg = await _store.GetAsync(TestGroupId);
        Assert.NotNull(reg);
        Assert.True(reg.Active);
        Assert.False(reg.PushEnabled);

        var replyText = TestFactory.GetLastReplyText(httpHandler);
        Assert.NotNull(replyText);
        Assert.Contains("TestBot", replyText);
    }

    [Fact]
    public async Task LeaveEventTombstonesGroup()
    {
        var config = BuildConfig();
        var httpHandler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var reply = TestFactory.CreateReplyService(config, httpHandler);
        var handler = new JoinLeaveHandler(_store, reply, config, NullLogger<JoinLeaveHandler>.Instance);

        await _store.UpsertJoinAsync(TestGroupId, 1000, "evt0");

        var leaveEvt = new LineEvent
        {
            Type = "leave",
            Source = new LineSource { Type = "group", GroupId = TestGroupId },
            Timestamp = 2000,
            WebhookEventId = "evt1"
        };

        var result = await handler.HandleAsync(leaveEvt, CancellationToken.None);
        Assert.True(result);

        var reg = await _store.GetAsync(TestGroupId);
        Assert.NotNull(reg);
        Assert.False(reg.Active);
    }

    [Fact]
    public async Task NonJoinLeaveEventReturnsFalse()
    {
        var config = BuildConfig();
        var httpHandler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var reply = TestFactory.CreateReplyService(config, httpHandler);
        var handler = new JoinLeaveHandler(_store, reply, config, NullLogger<JoinLeaveHandler>.Instance);

        var evt = new LineEvent { Type = "message", WebhookEventId = "x" };
        Assert.False(await handler.HandleAsync(evt, CancellationToken.None));
    }
}

public class DispatcherJoinLeaveTests
{
    private static IConfiguration BuildConfig() =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Line:ChannelAccessToken"] = "fake-token"
            }).Build();

    [Fact]
    public async Task JoinEventIsDispatchedToHandler()
    {
        var handled = false;
        var joinHandler = new TestJoinLeaveHandler(() => handled = true);
        var metrics = new FakeWebhookMetrics();
        var config = BuildConfig();
        var httpHandler = new RecordingHttpMessageHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var httpClient = new HttpClient(httpHandler);
        var reply = new LineReplyService(httpClient, config, metrics, NullLogger<LineReplyService>.Instance);
        var loading = new LoadingIndicatorService(httpClient, config, NullLogger<LoadingIndicatorService>.Instance);

        var dispatcher = new LineWebhookDispatcher(
            new StaticResultTextHandler(true),
            new StaticResultImageHandler(true),
            new StaticResultFileHandler(true),
            reply, loading, config,
            new NoopAdvisoryPostbackHandler(),
            joinHandler,
            metrics,
            NullLogger<LineWebhookDispatcher>.Instance);

        var evt = new LineEvent
        {
            Type = "join",
            Source = new LineSource { Type = "group", GroupId = "C" + new string('a', 32) },
            Timestamp = 1000,
            WebhookEventId = "evt1"
        };

        await dispatcher.DispatchAsync(evt, "http://test", CancellationToken.None);
        Assert.True(handled);
        Assert.True(metrics.MessageHandledByType.ContainsKey("join"));
    }

    private sealed class TestJoinLeaveHandler(Action onHandle) : IJoinLeaveHandler
    {
        public Task<bool> HandleAsync(LineEvent evt, CancellationToken ct)
        {
            onHandle();
            return Task.FromResult(true);
        }
    }

    private sealed class StaticResultTextHandler(bool result) : ITextMessageHandler
    {
        public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct) => Task.FromResult(result);
    }

    private sealed class StaticResultImageHandler(bool result) : IImageMessageHandler
    {
        public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct) => Task.FromResult(result);
    }

    private sealed class StaticResultFileHandler(bool result) : IFileMessageHandler
    {
        public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct) => Task.FromResult(result);
    }

    private sealed class NoopAdvisoryPostbackHandler : IAdvisoryPostbackHandler
    {
        public Task<bool> TryHandleAsync(LineEvent evt, IReadOnlyDictionary<string, string> parameters, CancellationToken ct)
            => Task.FromResult(false);
    }
}

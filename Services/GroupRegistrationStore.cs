using Microsoft.Data.Sqlite;

namespace LineBotWebhook.Services;

public record GroupRegistration(
    string GroupId,
    bool Active,
    bool PushEnabled,
    DateTime JoinedAt,
    DateTime? LeftAt,
    long LastEventTimestamp,
    string? LastWebhookEventId,
    DateTime UpdatedAt);

public class GroupRegistrationStore : IDisposable
{
    private readonly SqliteConnection _conn;
    private readonly SemaphoreSlim _lock = new(1, 1);
    private readonly ILogger<GroupRegistrationStore> _logger;

    public GroupRegistrationStore(string dbPath, ILogger<GroupRegistrationStore> logger)
    {
        _logger = logger;
        var dir = Path.GetDirectoryName(dbPath);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        _conn = new SqliteConnection($"Data Source={dbPath}");
        _conn.Open();

        using var cmd = _conn.CreateCommand();
        cmd.CommandText = """
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=5000;

            CREATE TABLE IF NOT EXISTS group_registrations (
                group_id             TEXT PRIMARY KEY,
                active               INTEGER NOT NULL DEFAULT 0,
                push_enabled         INTEGER NOT NULL DEFAULT 0,
                joined_at            TEXT NOT NULL,
                left_at              TEXT,
                last_event_timestamp INTEGER NOT NULL DEFAULT 0,
                last_webhook_event_id TEXT,
                updated_at           TEXT NOT NULL
            );
            """;
        cmd.ExecuteNonQuery();
    }

    public async Task<bool> UpsertJoinAsync(string groupId, long eventTimestamp, string webhookEventId, CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            var existing = ReadRow(groupId);
            if (existing is not null && eventTimestamp < existing.LastEventTimestamp)
            {
                _logger.LogDebug("Skipped stale join event. GroupId={GroupIdFingerprint} EventTs={EventTs} StoredTs={StoredTs}",
                    Fingerprint(groupId), eventTimestamp, existing.LastEventTimestamp);
                return false;
            }

            if (existing is not null && existing.LastWebhookEventId == webhookEventId)
            {
                _logger.LogDebug("Skipped duplicate join event. GroupId={GroupIdFingerprint} WebhookEventId={WebhookEventId}",
                    Fingerprint(groupId), webhookEventId);
                return false;
            }

            var now = DateTime.UtcNow.ToString("O");
            using var cmd = _conn.CreateCommand();
            cmd.CommandText = """
                INSERT INTO group_registrations (group_id, active, push_enabled, joined_at, left_at, last_event_timestamp, last_webhook_event_id, updated_at)
                VALUES (@gid, 1, 0, @now, NULL, @ts, @eid, @now)
                ON CONFLICT(group_id) DO UPDATE SET
                    active = 1,
                    left_at = NULL,
                    last_event_timestamp = @ts,
                    last_webhook_event_id = @eid,
                    updated_at = @now;
                """;
            cmd.Parameters.AddWithValue("@gid", groupId);
            cmd.Parameters.AddWithValue("@now", now);
            cmd.Parameters.AddWithValue("@ts", eventTimestamp);
            cmd.Parameters.AddWithValue("@eid", webhookEventId);
            cmd.ExecuteNonQuery();

            _logger.LogInformation("Group joined. GroupId={GroupIdFingerprint}", Fingerprint(groupId));
            return true;
        }
        finally
        {
            _lock.Release();
        }
    }

    public async Task<bool> UpsertLeaveAsync(string groupId, long eventTimestamp, string webhookEventId, CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            var existing = ReadRow(groupId);
            if (existing is not null && eventTimestamp < existing.LastEventTimestamp)
            {
                _logger.LogDebug("Skipped stale leave event. GroupId={GroupIdFingerprint} EventTs={EventTs} StoredTs={StoredTs}",
                    Fingerprint(groupId), eventTimestamp, existing.LastEventTimestamp);
                return false;
            }

            if (existing is not null && existing.LastWebhookEventId == webhookEventId)
                return false;

            var now = DateTime.UtcNow.ToString("O");
            using var cmd = _conn.CreateCommand();
            cmd.CommandText = """
                INSERT INTO group_registrations (group_id, active, push_enabled, joined_at, left_at, last_event_timestamp, last_webhook_event_id, updated_at)
                VALUES (@gid, 0, 0, @now, @now, @ts, @eid, @now)
                ON CONFLICT(group_id) DO UPDATE SET
                    active = 0,
                    push_enabled = 0,
                    left_at = @now,
                    last_event_timestamp = @ts,
                    last_webhook_event_id = @eid,
                    updated_at = @now;
                """;
            cmd.Parameters.AddWithValue("@gid", groupId);
            cmd.Parameters.AddWithValue("@now", now);
            cmd.Parameters.AddWithValue("@ts", eventTimestamp);
            cmd.Parameters.AddWithValue("@eid", webhookEventId);
            cmd.ExecuteNonQuery();

            _logger.LogInformation("Group left (tombstoned). GroupId={GroupIdFingerprint}", Fingerprint(groupId));
            return true;
        }
        finally
        {
            _lock.Release();
        }
    }

    public async Task<GroupRegistration?> GetAsync(string groupId, CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            return ReadRow(groupId);
        }
        finally
        {
            _lock.Release();
        }
    }

    public async Task<bool> SetPushEnabledAsync(string groupId, bool enabled, CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            var existing = ReadRow(groupId);
            if (existing is null || !existing.Active)
                return false;

            using var cmd = _conn.CreateCommand();
            cmd.CommandText = "UPDATE group_registrations SET push_enabled = @pe, updated_at = @now WHERE group_id = @gid AND active = 1";
            cmd.Parameters.AddWithValue("@pe", enabled ? 1 : 0);
            cmd.Parameters.AddWithValue("@now", DateTime.UtcNow.ToString("O"));
            cmd.Parameters.AddWithValue("@gid", groupId);
            return cmd.ExecuteNonQuery() > 0;
        }
        finally
        {
            _lock.Release();
        }
    }

    public async Task<IReadOnlyList<GroupRegistration>> GetPushableGroupsAsync(CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            using var cmd = _conn.CreateCommand();
            cmd.CommandText = "SELECT * FROM group_registrations WHERE active = 1 AND push_enabled = 1";
            using var reader = cmd.ExecuteReader();
            var results = new List<GroupRegistration>();
            while (reader.Read())
                results.Add(MapRow(reader));
            return results;
        }
        finally
        {
            _lock.Release();
        }
    }

    public async Task IncrementPushFailureAsync(string groupId, CancellationToken ct = default)
    {
        var reg = await GetAsync(groupId, ct);
        if (reg is null)
            return;

        // 此處不另加 failure_count 欄位；由 LinePushService 外部計數，
        // 連續 3 次 403/404 時呼叫 SetPushEnabledAsync(false)。
    }

    private GroupRegistration? ReadRow(string groupId)
    {
        using var cmd = _conn.CreateCommand();
        cmd.CommandText = "SELECT * FROM group_registrations WHERE group_id = @gid";
        cmd.Parameters.AddWithValue("@gid", groupId);
        using var reader = cmd.ExecuteReader();
        return reader.Read() ? MapRow(reader) : null;
    }

    private static GroupRegistration MapRow(SqliteDataReader reader) => new(
        GroupId: reader.GetString(reader.GetOrdinal("group_id")),
        Active: reader.GetInt32(reader.GetOrdinal("active")) == 1,
        PushEnabled: reader.GetInt32(reader.GetOrdinal("push_enabled")) == 1,
        JoinedAt: DateTime.Parse(reader.GetString(reader.GetOrdinal("joined_at"))),
        LeftAt: reader.IsDBNull(reader.GetOrdinal("left_at")) ? null : DateTime.Parse(reader.GetString(reader.GetOrdinal("left_at"))),
        LastEventTimestamp: reader.GetInt64(reader.GetOrdinal("last_event_timestamp")),
        LastWebhookEventId: reader.IsDBNull(reader.GetOrdinal("last_webhook_event_id")) ? null : reader.GetString(reader.GetOrdinal("last_webhook_event_id")),
        UpdatedAt: DateTime.Parse(reader.GetString(reader.GetOrdinal("updated_at"))));

    private static string Fingerprint(string id) => id.Length > 8 ? id[..4] + "…" + id[^4..] : "****";

    public void Dispose()
    {
        _conn.Dispose();
        _lock.Dispose();
        GC.SuppressFinalize(this);
    }
}

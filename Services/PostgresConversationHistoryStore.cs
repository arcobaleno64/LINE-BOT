using System.Text.Json;
using Npgsql;

namespace LineBotWebhook.Services;

public sealed class PostgresConversationHistoryStore(NpgsqlDataSource dataSource)
{
    private const string TableName = "conversation_history";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly NpgsqlDataSource _dataSource = dataSource;

    public static string? ResolveConnectionString(IConfiguration configuration)
    {
        var value = configuration.GetConnectionString("Postgres");
        if (string.IsNullOrWhiteSpace(value))
            value = configuration["DATABASE_URL"];
        if (string.IsNullOrWhiteSpace(value))
            return null;

        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
            || (uri.Scheme is not ("postgres" or "postgresql")))
        {
            return value;
        }

        var userInfoSeparator = uri.UserInfo.IndexOf(':');
        if (userInfoSeparator < 0)
            throw new InvalidOperationException("DATABASE_URL must include a PostgreSQL username and password.");

        var builder = new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.IsDefaultPort ? 5432 : uri.Port,
            Database = Uri.UnescapeDataString(uri.AbsolutePath.TrimStart('/')),
            Username = Uri.UnescapeDataString(uri.UserInfo[..userInfoSeparator]),
            Password = Uri.UnescapeDataString(uri.UserInfo[(userInfoSeparator + 1)..]),
            SslMode = SslMode.Require
        };

        return builder.ConnectionString;
    }

    internal async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        await using var command = _dataSource.CreateCommand($"""
            CREATE TABLE IF NOT EXISTS {TableName} (
                user_key_hash text PRIMARY KEY,
                generation uuid NOT NULL,
                created_at_utc timestamptz NOT NULL,
                last_access_at_utc timestamptz NOT NULL,
                session_summary text NULL,
                messages jsonb NOT NULL,
                pending_summary_messages jsonb NULL,
                is_summarizing boolean NOT NULL,
                active_summary_id uuid NULL
            );
            ALTER TABLE conversation_history
                ADD COLUMN IF NOT EXISTS active_summary_id uuid NULL;
            UPDATE conversation_history
            SET active_summary_id = gen_random_uuid()
            WHERE is_summarizing
              AND pending_summary_messages IS NOT NULL
              AND active_summary_id IS NULL;
            CREATE INDEX IF NOT EXISTS ix_conversation_history_retention
                ON {TableName} (last_access_at_utc, created_at_utc);
            """);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    internal async Task<PersistedConversationSession?> LoadAsync(
        string userKeyHash,
        DateTime idleCutoffUtc,
        DateTime hardExpiryCutoffUtc,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await _dataSource.OpenConnectionAsync(cancellationToken);
        await using (var deleteExpired = new NpgsqlCommand($"""
            DELETE FROM {TableName}
            WHERE user_key_hash = $1
              AND (last_access_at_utc < $2 OR created_at_utc < $3)
            """, connection))
        {
            deleteExpired.Parameters.AddWithValue(userKeyHash);
            deleteExpired.Parameters.AddWithValue(idleCutoffUtc);
            deleteExpired.Parameters.AddWithValue(hardExpiryCutoffUtc);
            await deleteExpired.ExecuteNonQueryAsync(cancellationToken);
        }

        await using var command = new NpgsqlCommand($"""
            SELECT generation, created_at_utc, last_access_at_utc, session_summary,
                   messages::text, pending_summary_messages::text, is_summarizing, active_summary_id
            FROM {TableName}
            WHERE user_key_hash = $1
            """, connection);
        command.Parameters.AddWithValue(userKeyHash);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        return await reader.ReadAsync(cancellationToken)
            ? ReadSession(reader)
            : null;
    }

    internal async Task<PersistedConversationSession?> MutateAsync(
        string userKeyHash,
        DateTime idleCutoffUtc,
        DateTime hardExpiryCutoffUtc,
        Func<PersistedConversationSession?, PersistedConversationSession?> update,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await _dataSource.OpenConnectionAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);

        await using (var lockCommand = new NpgsqlCommand(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            connection,
            transaction))
        {
            lockCommand.Parameters.AddWithValue(userKeyHash);
            await lockCommand.ExecuteScalarAsync(cancellationToken);
        }

        var current = await LoadForUpdateAsync(connection, transaction, userKeyHash, cancellationToken);
        if (current is not null
            && (current.LastAccessAtUtc < idleCutoffUtc || current.CreatedAtUtc < hardExpiryCutoffUtc))
        {
            current = null;
        }

        var updated = update(current);
        if (updated is null)
        {
            await using var deleteCommand = new NpgsqlCommand($"DELETE FROM {TableName} WHERE user_key_hash = $1", connection, transaction);
            deleteCommand.Parameters.AddWithValue(userKeyHash);
            await deleteCommand.ExecuteNonQueryAsync(cancellationToken);
        }
        else
        {
            await SaveAsync(connection, transaction, userKeyHash, updated, cancellationToken);
        }
        await PruneToSessionLimitAsync(connection, transaction, cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return updated;
    }

    internal async Task DeleteAsync(string userKeyHash, CancellationToken cancellationToken = default)
    {
        await using var connection = await _dataSource.OpenConnectionAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);
        await using (var lockCommand = new NpgsqlCommand(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            connection,
            transaction))
        {
            lockCommand.Parameters.AddWithValue(userKeyHash);
            await lockCommand.ExecuteScalarAsync(cancellationToken);
        }

        await using var command = new NpgsqlCommand($"DELETE FROM {TableName} WHERE user_key_hash = $1", connection, transaction);
        command.Parameters.AddWithValue(userKeyHash);
        await command.ExecuteNonQueryAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
    }

    internal async Task<IReadOnlyList<ConversationSummaryWorkItem>> GetPendingSummaryWorkItemsAsync(
        DateTime idleCutoffUtc,
        DateTime hardExpiryCutoffUtc,
        CancellationToken cancellationToken = default)
    {
        var items = new List<ConversationSummaryWorkItem>();
        await using var command = _dataSource.CreateCommand($"""
            SELECT user_key_hash, generation, active_summary_id,
                   jsonb_array_length(pending_summary_messages),
                   jsonb_array_length(messages)
            FROM {TableName}
            WHERE is_summarizing
              AND active_summary_id IS NOT NULL
              AND pending_summary_messages IS NOT NULL
              AND last_access_at_utc >= $1
              AND created_at_utc >= $2
            ORDER BY last_access_at_utc
            """);
        command.Parameters.AddWithValue(idleCutoffUtc);
        command.Parameters.AddWithValue(hardExpiryCutoffUtc);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            var keyHash = reader.GetString(0);
            items.Add(new ConversationSummaryWorkItem(
                UserKey: string.Empty,
                SessionId: reader.GetGuid(1),
                SummaryId: reader.GetGuid(2),
                UserKeyFingerprint: ObservabilityKeyFingerprint.From(keyHash),
                EnqueuedAtUtc: DateTime.UtcNow,
                PendingCount: reader.GetInt32(3),
                MessageCount: reader.GetInt32(4),
                UserKeyHash: keyHash));
        }

        return items;
    }
    internal async Task<int> DeleteExpiredAsync(
        DateTime idleCutoffUtc,
        DateTime hardExpiryCutoffUtc,
        CancellationToken cancellationToken = default)
    {
        await using var command = _dataSource.CreateCommand($"""
            DELETE FROM {TableName}
            WHERE last_access_at_utc < $1 OR created_at_utc < $2
            """);
        command.Parameters.AddWithValue(idleCutoffUtc);
        command.Parameters.AddWithValue(hardExpiryCutoffUtc);
        return await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static async Task<PersistedConversationSession?> LoadForUpdateAsync(
        NpgsqlConnection connection,
        NpgsqlTransaction transaction,
        string userKeyHash,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand($"""
            SELECT generation, created_at_utc, last_access_at_utc, session_summary,
                   messages::text, pending_summary_messages::text, is_summarizing, active_summary_id
            FROM {TableName}
            WHERE user_key_hash = $1
            FOR UPDATE
            """, connection, transaction);
        command.Parameters.AddWithValue(userKeyHash);
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        return await reader.ReadAsync(cancellationToken)
            ? ReadSession(reader)
            : null;
    }

    private static PersistedConversationSession ReadSession(NpgsqlDataReader reader)
    {
        var messages = JsonSerializer.Deserialize<List<ConversationHistoryService.ChatMessage>>(reader.GetString(4), JsonOptions) ?? [];
        var pendingJson = reader.IsDBNull(5) ? null : reader.GetString(5);
        var pendingMessages = pendingJson is null
            ? null
            : JsonSerializer.Deserialize<List<ConversationHistoryService.ChatMessage>>(pendingJson, JsonOptions);

        return new PersistedConversationSession(
            reader.GetGuid(0),
            reader.GetDateTime(1),
            reader.GetDateTime(2),
            reader.IsDBNull(3) ? null : reader.GetString(3),
            messages,
            pendingMessages,
            reader.GetBoolean(6),
            reader.IsDBNull(7) ? null : reader.GetGuid(7));
    }

    private static async Task SaveAsync(
        NpgsqlConnection connection,
        NpgsqlTransaction transaction,
        string userKeyHash,
        PersistedConversationSession session,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand($"""
            INSERT INTO {TableName}
                (user_key_hash, generation, created_at_utc, last_access_at_utc,
                 session_summary, messages, pending_summary_messages, is_summarizing, active_summary_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
            ON CONFLICT (user_key_hash) DO UPDATE SET
                generation = EXCLUDED.generation,
                created_at_utc = EXCLUDED.created_at_utc,
                last_access_at_utc = EXCLUDED.last_access_at_utc,
                session_summary = EXCLUDED.session_summary,
                messages = EXCLUDED.messages,
                pending_summary_messages = EXCLUDED.pending_summary_messages,
                is_summarizing = EXCLUDED.is_summarizing,
                active_summary_id = EXCLUDED.active_summary_id
            """, connection, transaction);
        command.Parameters.AddWithValue(userKeyHash);
        command.Parameters.AddWithValue(session.Generation);
        command.Parameters.AddWithValue(session.CreatedAtUtc);
        command.Parameters.AddWithValue(session.LastAccessAtUtc);
        command.Parameters.AddWithValue((object?)session.SessionSummary ?? DBNull.Value);
        command.Parameters.AddWithValue(JsonSerializer.Serialize(session.Messages, JsonOptions));
        command.Parameters.AddWithValue((object?)(session.PendingSummaryMessages is null
            ? null
            : JsonSerializer.Serialize(session.PendingSummaryMessages, JsonOptions)) ?? DBNull.Value);
        command.Parameters.AddWithValue(session.IsSummarizing);
        command.Parameters.AddWithValue((object?)session.ActiveSummaryId ?? DBNull.Value);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static async Task PruneToSessionLimitAsync(
        NpgsqlConnection connection,
        NpgsqlTransaction transaction,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand($"""
            DELETE FROM {TableName}
            WHERE user_key_hash IN (
                SELECT user_key_hash
                FROM {TableName}
                ORDER BY last_access_at_utc DESC
                OFFSET 1000
            )
            """, connection, transaction);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }
}

internal sealed record PersistedConversationSession(
    Guid Generation,
    DateTime CreatedAtUtc,
    DateTime LastAccessAtUtc,
    string? SessionSummary,
    List<ConversationHistoryService.ChatMessage> Messages,
    List<ConversationHistoryService.ChatMessage>? PendingSummaryMessages,
    bool IsSummarizing,
    Guid? ActiveSummaryId = null);

public sealed class ConversationHistoryStoreInitializer(
    PostgresConversationHistoryStore store,
    ConversationHistoryService history,
    ILogger<ConversationHistoryStoreInitializer> logger) : IHostedService
{
    public async Task StartAsync(CancellationToken cancellationToken)
    {
        await store.InitializeAsync(cancellationToken);
        history.MarkPersistenceReady();
        logger.LogInformation("PostgreSQL conversation history store initialized");
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}

public sealed class ConversationHistoryCleanupWorker(
    PostgresConversationHistoryStore store,
    ILogger<ConversationHistoryCleanupWorker> logger) : BackgroundService
{
    private static readonly TimeSpan IdleRetention = TimeSpan.FromHours(8);
    private static readonly TimeSpan MaximumRetention = TimeSpan.FromDays(30);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromHours(1));
        do
        {
            try
            {
                var now = DateTime.UtcNow;
                var deleted = await store.DeleteExpiredAsync(
                    now - IdleRetention,
                    now - MaximumRetention,
                    stoppingToken);
                if (deleted > 0)
                    logger.LogInformation("Expired conversation history removed. SessionCount={SessionCount}", deleted);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                logger.LogError("Conversation history cleanup failed. ExceptionType={ExceptionType}", ex.GetType().Name);
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }
}

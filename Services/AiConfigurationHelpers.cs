namespace LineBotWebhook.Services;

internal static class AiConfigurationHelpers
{
    public static string? GetConfiguredValue(IConfiguration config, string key)
    {
        var value = config[key]?.Trim();
        return IsConfiguredValue(value) ? value : null;
    }

    public static IReadOnlyList<string> GetConfiguredValues(IConfiguration config, params string[] keys)
    {
        return keys
            .Select(key => GetConfiguredValue(config, key))
            .Where(static value => value is not null)
            .Cast<string>()
            .Distinct(StringComparer.Ordinal)
            .ToArray();
    }

    public static bool IsConfiguredValue(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return false;

        return !(value.StartsWith('<') && value.EndsWith('>'));
    }
}

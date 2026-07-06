using System.Globalization;

namespace DiabetesApi.Routes;

/// <summary>
/// Shared time-range resolution utilities for API route controllers.
/// </summary>
public static class TimeRangeUtils
{
    /// <summary>
    /// Resolves a (start, end) <see cref="DateTime"/> window from the supplied query parameters.
    /// </summary>
    /// <remarks>
    /// Call this method <b>only when at least one of <paramref name="start"/> / <paramref name="end"/> is null</b>.
    /// When both are already provided by the caller, use them directly.
    ///
    /// Resolution rules (in priority order):
    /// <list type="number">
    ///   <item><description><c>start + end</c> both provided → callers skip this method entirely.</description></item>
    ///   <item><description><c>start + last</c> → <c>end = start + last</c></description></item>
    ///   <item><description><c>end + last</c>   → <c>start = end − last</c></description></item>
    ///   <item><description><c>last</c> only    → <c>end = latestTimestamp ?? UtcNow</c>, <c>start = end − last</c></description></item>
    ///   <item><description>none provided       → uses <paramref name="defaultLast"/> (defaults to <c>"2w"</c>)</description></item>
    /// </list>
    /// </remarks>
    /// <param name="last">Period string such as "24h", "7d", "2w", "1m" (optional).</param>
    /// <param name="start">ISO 8601 datetime string for window start (optional).</param>
    /// <param name="end">ISO 8601 datetime string for window end (optional).</param>
    /// <param name="getLatestTimestamp">
    /// Async factory that returns the most recent record timestamp for the relevant table.
    /// Only invoked when <paramref name="end"/> is null. Falls back to <see cref="DateTime.UtcNow"/> when null or returns null.
    /// </param>
    /// <param name="defaultLast">Fallback period when no parameters are supplied (default <c>"2w"</c>).</param>
    /// <returns>
    /// A <c>(DateTime start, DateTime end)</c> tuple on success, or <c>null</c> when <paramref name="last"/> is malformed.
    /// </returns>
    public static async Task<(DateTime start, DateTime end)?> ResolveTimeRangeAsync(
        string?  last               = null,
        string?  start              = null,
        string?  end                = null,
        Func<Task<DateTime?>>? getLatestTimestamp = null,
        string   defaultLast        = "2w")
    {
        // Apply default period when nothing is specified.
        if (start is null && end is null && last is null)
            last = defaultLast;

        // ---------- Parse anchors ------------------------------------------------
        DateTime? startDt = start is not null
            ? DateTime.Parse(start, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind).ToUniversalTime()
            : null;

        DateTime? endDt = end is not null
            ? DateTime.Parse(end, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind).ToUniversalTime()
            : null;

        // Both anchors explicit → callers should have short-circuited; return as-is.
        if (startDt is not null && endDt is not null)
            return (startDt.Value, endDt.Value);

        // ---------- Apply 'last' --------------------------------------------------
        if (last is not null)
        {
            // Case: start + last → end = start + last
            if (startDt is not null)
            {
                var span = ParsePeriod(last);
                if (span is null) return null;
                endDt = AddPeriod(startDt.Value, span.Value);
                return (startDt.Value, endDt.Value);
            }

            // Case: end + last, or last only.
            // Resolve end if not yet provided.
            if (endDt is null)
            {
                DateTime? latest = getLatestTimestamp is not null
                    ? await getLatestTimestamp()
                    : null;
                endDt = latest.HasValue
                    ? DateTime.SpecifyKind(latest.Value, DateTimeKind.Utc)
                    : DateTime.UtcNow;
            }

            var spanBack = ParsePeriod(last);
            if (spanBack is null) return null;
            startDt = SubtractPeriod(endDt.Value, spanBack.Value);
            return (startDt.Value, endDt.Value);
        }

        // ---------- No 'last', only one anchor provided --------------------------
        // Shouldn't normally happen, but handle gracefully with the default period.
        if (startDt is not null)
        {
            var fallback = ParsePeriod(defaultLast)!.Value;
            endDt = AddPeriod(startDt.Value, fallback);
            return (startDt.Value, endDt.Value);
        }
        if (endDt is not null)
        {
            var fallback = ParsePeriod(defaultLast)!.Value;
            startDt = SubtractPeriod(endDt.Value, fallback);
            return (startDt.Value, endDt.Value);
        }

        // Should never reach here (covered by the default-last assignment above).
        return null;
    }

    /// <summary>
    /// Parses a period string (e.g. "24h", "7d", "2w", "1m") into a
    /// <see cref="PeriodSpec"/> value object.  Returns <c>null</c> if malformed.
    /// </summary>
    public static PeriodSpec? ParsePeriod(string last)
    {
        if (last.Length < 2) return null;
        if (!int.TryParse(last[..^1], out int n) || n <= 0) return null;
        return last[^1] switch
        {
            'h' => new PeriodSpec(PeriodUnit.Hours,  n),
            'd' => new PeriodSpec(PeriodUnit.Days,   n),
            'w' => new PeriodSpec(PeriodUnit.Weeks,  n),
            'm' => new PeriodSpec(PeriodUnit.Months, n),
            _   => null
        };
    }

    // ── helpers ──────────────────────────────────────────────────────────────────

    private static DateTime AddPeriod(DateTime dt, PeriodSpec p) => p.Unit switch
    {
        PeriodUnit.Hours  => dt.AddHours(p.N),
        PeriodUnit.Days   => dt.AddDays(p.N),
        PeriodUnit.Weeks  => dt.AddDays(p.N * 7),
        PeriodUnit.Months => dt.AddMonths(p.N),
        _                 => dt
    };

    private static DateTime SubtractPeriod(DateTime dt, PeriodSpec p) => p.Unit switch
    {
        PeriodUnit.Hours  => dt.AddHours(-p.N),
        PeriodUnit.Days   => dt.AddDays(-p.N),
        PeriodUnit.Weeks  => dt.AddDays(-p.N * 7),
        PeriodUnit.Months => dt.AddMonths(-p.N),
        _                 => dt
    };
}

/// <summary>Unit of a time period.</summary>
public enum PeriodUnit { Hours, Days, Weeks, Months }

/// <summary>Parsed representation of a period string (e.g. "7d" → Days/7).</summary>
public readonly record struct PeriodSpec(PeriodUnit Unit, int N);

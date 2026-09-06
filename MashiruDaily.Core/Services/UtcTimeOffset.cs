using System;

namespace MashiruDaily.Core.Services;

/// <summary>
/// 统一使用 UTC+8 作为系统时间标准。
/// </summary>
public static class UtcTimeOffset
{
    /// <summary>
    /// UTC+8 固定偏移。
    /// </summary>
    public static TimeSpan Offset { get; } = TimeSpan.FromHours(8);

    /// <summary>
    /// 当前 UTC+8 墙钟时间；<see cref="DateTimeKind.Unspecified"/>，表示“UTC+8 本地墙上时间”。
    /// </summary>
    public static DateTime Now => DateTime.SpecifyKind(DateTime.UtcNow.Add(Offset), DateTimeKind.Unspecified);

    /// <summary>
    /// 当前 UTC+8 的 <see cref="DateTimeOffset"/>。
    /// </summary>
    public static DateTimeOffset NowOffset => new(DateTime.SpecifyKind(DateTime.UtcNow.Add(Offset), DateTimeKind.Unspecified), Offset);

    /// <summary>
    /// 将任意 <see cref="DateTime"/> 转换为 UTC+8 墙钟时间（<see cref="DateTimeKind.Unspecified"/>）。
    /// <see cref="DateTimeKind.Unspecified"/> 视为已经是 UTC+8 墙钟时间。
    /// </summary>
    public static DateTime ToChinaWallClock(DateTime value)
    {
        if (value.Kind == DateTimeKind.Utc)
        {
            return DateTime.SpecifyKind(value.Add(Offset), DateTimeKind.Unspecified);
        }

        if (value.Kind == DateTimeKind.Local)
        {
            return DateTime.SpecifyKind(TimeZoneInfo.ConvertTimeToUtc(value).Add(Offset), DateTimeKind.Unspecified);
        }

        return value;
    }

    /// <summary>
    /// 将任意 <see cref="DateTime"/> 转换为带 UTC+8 偏移的 <see cref="DateTimeOffset"/>。
    /// </summary>
    public static DateTimeOffset ToChinaOffset(DateTime value)
        => new(ToChinaWallClock(value), Offset);
}

using System;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace MashiruDaily.Core.Converters;

/// <summary>
/// 将 <see cref="DateTime"/> 序列化为带时区偏移的 ISO 8601 字符串
/// （如 <c>2026-08-13T10:30:00+08:00</c>），与通信协议及服务器 todo.json
/// 的字段格式对齐；对 <see cref="DateTime?"/> 自动生效（Nullable 包装）。
/// <see cref="DateTimeKind.Unspecified"/> 按本地时间解释；
/// <see cref="DateTimeKind.Utc"/> 输出 <c>Z</c> 后缀。
/// 反序列化沿用 System.Text.Json 默认语义，保持行为不变。
/// </summary>
public sealed class LocalDateTimeJsonConverter : JsonConverter<DateTime>
{
    /// <inheritdoc />
    public override DateTime Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        => reader.GetDateTime();

    /// <inheritdoc />
    public override void Write(Utf8JsonWriter writer, DateTime value, JsonSerializerOptions options)
    {
        if (value.Kind == DateTimeKind.Utc)
        {
            writer.WriteStringValue(value.ToString("yyyy-MM-ddTHH:mm:ss.FFFFFFF'Z'", CultureInfo.InvariantCulture));
            return;
        }

        // Unspecified（如旧版无偏移数据）按本地时间解释，保留时刻值不变
        var dt = value.Kind == DateTimeKind.Unspecified
            ? DateTime.SpecifyKind(value, DateTimeKind.Local)
            : value;
        writer.WriteStringValue(
            new DateTimeOffset(dt).ToString("yyyy-MM-ddTHH:mm:ss.FFFFFFFzzz", CultureInfo.InvariantCulture));
    }
}

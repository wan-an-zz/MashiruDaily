using System;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using MashiruDaily.Core.Services;

namespace MashiruDaily.Core.Converters;

/// <summary>
/// 将 <see cref="DateTime"/> 统一序列化为 UTC+8 的 ISO 8601 字符串
/// （如 <c>2026-08-13T10:30:00.1234567+08:00</c>），与通信协议及服务器 todo.json
/// 的字段格式对齐；对 <see cref="DateTime?"/> 自动生效（Nullable 包装）。
/// 反序列化时也统一按 UTC+8 墙钟时间解释，避免不同机器本地时区造成偏差。
/// </summary>
public sealed class LocalDateTimeJsonConverter : JsonConverter<DateTime>
{
    /// <inheritdoc />
    public override DateTime Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        var dto = reader.GetDateTimeOffset();
        return UtcTimeOffset.ToChinaWallClock(dto.UtcDateTime);
    }

    /// <inheritdoc />
    public override void Write(Utf8JsonWriter writer, DateTime value, JsonSerializerOptions options)
    {
        writer.WriteStringValue(
            UtcTimeOffset.ToChinaOffset(value).ToString("yyyy-MM-ddTHH:mm:ss.FFFFFFFzzz", CultureInfo.InvariantCulture));
    }
}

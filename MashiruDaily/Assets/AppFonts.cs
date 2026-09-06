using Avalonia.Media;

namespace MashiruDaily.Assets;

/// <summary>
/// 各平台共享的字体配置。
///
/// Android 后端对操作系统字体集合的字形回退不可靠
/// （参见 https://github.com/AvaloniaUI/Avalonia/issues/19868 与 #19931），
/// 因此不含 CJK 覆盖的字体（如 Inter）中的中文字符会渲染为空格。
/// 为保证各平台渲染一致，我们内置 Noto Sans SC 子集并注册为显式回退。
/// </summary>
public static class AppFonts
{
    private static readonly FontFamily CjkFont = new("fonts:MashiruDailyCJK#Noto Sans SC");

    public static FontManagerOptions CreateFontManagerOptions() => new()
    {
        FontFallbacks = new FontFallback[]
        {
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0x3000, 0x303F) }, // CJK 符号与标点
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0x3400, 0x4DBF) }, // CJK 扩展 A
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0x4E00, 0x9FFF) }, // CJK 统一表意文字
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0xF900, 0xFAFF) }, // CJK 兼容表意文字
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0xFF00, 0xFFEF) }, // 全角形式
        },
    };
}

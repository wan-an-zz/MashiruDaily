using Avalonia.Media;

namespace MashiruDaily.Assets;

/// <summary>
/// Shared font configuration used by every platform.
///
/// The Android backend has an unreliable glyph-fallback to the OS font collection
/// (see https://github.com/AvaloniaUI/Avalonia/issues/19868 and #19931), so CJK
/// characters in a font without CJK coverage (e.g. Inter) render as empty boxes.
/// To make rendering deterministic across platforms we bundle a subset of
/// Noto Sans SC and register it as an explicit fallback.
/// </summary>
public static class AppFonts
{
    private static readonly FontFamily CjkFont = new("fonts:MashiruDailyCJK#Noto Sans SC");

    public static FontManagerOptions CreateFontManagerOptions() => new()
    {
        FontFallbacks = new FontFallback[]
        {
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0x3000, 0x303F) }, // CJK symbols & punctuation
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0x3400, 0x4DBF) }, // CJK Extension A
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0x4E00, 0x9FFF) }, // CJK unified ideographs
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0xF900, 0xFAFF) }, // CJK compatibility ideographs
            new FontFallback { FontFamily = CjkFont, UnicodeRange = new UnicodeRange(0xFF00, 0xFFEF) }, // fullwidth forms
        },
    };
}

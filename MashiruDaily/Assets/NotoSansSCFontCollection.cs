using System;
using Avalonia.Media.Fonts;

namespace MashiruDaily.Assets;

/// <summary>
/// Registers the bundled Noto Sans SC subset so it can be referenced as
/// <c>fonts:MashiruDailyCJK#Noto Sans SC</c>.
/// </summary>
public sealed class NotoSansSCFontCollection : EmbeddedFontCollection
{
    public NotoSansSCFontCollection() : base(
        new Uri("fonts:MashiruDailyCJK", UriKind.Absolute),
        new Uri("avares://MashiruDaily/Assets/Fonts", UriKind.Absolute))
    {
    }
}

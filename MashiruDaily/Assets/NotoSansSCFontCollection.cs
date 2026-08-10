using System;
using Avalonia.Media.Fonts;

namespace MashiruDaily.Assets;

/// <summary>
/// 注册内置的 Noto Sans SC 子集，使其可通过
/// <c>fonts:MashiruDailyCJK#Noto Sans SC</c> 引用。
/// </summary>
public sealed class NotoSansSCFontCollection : EmbeddedFontCollection
{
    public NotoSansSCFontCollection() : base(
        new Uri("fonts:MashiruDailyCJK", UriKind.Absolute),
        new Uri("avares://MashiruDaily/Assets/Fonts", UriKind.Absolute))
    {
    }
}

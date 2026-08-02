using Avalonia.Media;
using MashiruDaily.ViewModels;

namespace MashiruDaily.Abstracts;

/// <summary>
/// A navigable application section. Keeps navigation metadata (label + icon)
/// decoupled from the page itself so it can be reused by any navigation UI.
/// </summary>
public interface INavigationItem
{
    /// <summary>Menu / tab label, e.g. "Todo".</summary>
    string Header { get; }

    /// <summary>Icon geometry shown next to the label.</summary>
    StreamGeometry Icon { get; }

    /// <summary>The page view-model shown when this item is active.</summary>
    ViewModelBase Page { get; }
}

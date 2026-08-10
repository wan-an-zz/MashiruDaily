using Avalonia.Media;
using MashiruDaily.Abstracts;
using MashiruDaily.Core.ViewModels;

namespace MashiruDaily.Models;

/// <summary>
/// Concrete <see cref="INavigationItem"/> used by both the desktop side menu
/// and the mobile bottom navigation bar.
/// </summary>
public sealed class NavigationItem : INavigationItem
{
    public NavigationItem(string header, StreamGeometry icon, ViewModelBase page)
    {
        Header = header;
        Icon = icon;
        Page = page;
    }

    public string Header { get; }

    public StreamGeometry Icon { get; }

    public ViewModelBase Page { get; }
}

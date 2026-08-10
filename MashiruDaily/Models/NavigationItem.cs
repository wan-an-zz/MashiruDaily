using Avalonia.Media;
using MashiruDaily.Abstracts;
using MashiruDaily.Core.ViewModels;

namespace MashiruDaily.Models;

/// <summary>
/// 桌面侧边菜单与移动端底部导航栏共用的 <see cref="INavigationItem"/> 具体实现。
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

using Avalonia.Media;
using MashiruDaily.Core.ViewModels;

namespace MashiruDaily.Abstracts;

/// <summary>
/// 可导航的应用分区。将导航元数据（标签 + 图标）与页面本身解耦，
/// 以便任何导航 UI 复用。
/// </summary>
public interface INavigationItem
{
    /// <summary>菜单 / 标签文字，例如 "Todo"。</summary>
    string Header { get; }

    /// <summary>显示在标签旁的图标几何。</summary>
    StreamGeometry Icon { get; }

    /// <summary>该条目激活时显示的页面视图模型。</summary>
    ViewModelBase Page { get; }
}

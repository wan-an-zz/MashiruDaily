using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using MashiruDaily.Abstracts;
using MashiruDaily.Assets;
using MashiruDaily.Models;
using MashiruDaily.ViewModels.Todo;

namespace MashiruDaily.ViewModels;

/// <summary>
/// Root view-model. Exposes the available navigation items and which one is
/// active. The same items are consumed by the desktop side menu
/// (<c>SukiSideMenu</c>) and the mobile bottom navigation bar.
/// </summary>
public partial class MainViewModel : ViewModelBase
{
    public MainViewModel(TodoPageViewModel todoPage)
    {
        TodoPage = todoPage;
        NavigationItems = new ObservableCollection<INavigationItem>
        {
            new NavigationItem("Todo List", AppIcons.Todo, todoPage),
        };

        _activeItem = NavigationItems[0];
        _activeIndex = 0;
    }

    public TodoPageViewModel TodoPage { get; }

    public ObservableCollection<INavigationItem> NavigationItems { get; }

    [ObservableProperty]
    private INavigationItem? _activeItem;

    [ObservableProperty]
    private int _activeIndex;

    partial void OnActiveItemChanged(INavigationItem? value)
    {
        if (value is null)
            return;

        var index = NavigationItems.IndexOf(value);
        if (index >= 0 && ActiveIndex != index)
            ActiveIndex = index;
    }

    partial void OnActiveIndexChanged(int value)
    {
        if (value < 0 || value >= NavigationItems.Count)
            return;

        var item = NavigationItems[value];
        if (!ReferenceEquals(ActiveItem, item))
            ActiveItem = item;
    }
}

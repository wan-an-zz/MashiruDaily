using System.Collections.ObjectModel;
using System.Threading.Tasks;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using MashiruDaily.Abstracts;
using MashiruDaily.Assets;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.ViewModels;
using MashiruDaily.Core.ViewModels.Todo;
using MashiruDaily.Models;
using CommunityToolkit.Mvvm.Input;

namespace MashiruDaily.ViewModels;

/// <summary>
/// Root view-model. Exposes the available navigation items and which one is
/// active. The same items are consumed by the desktop side menu
/// (<c>SukiSideMenu</c>) and the mobile bottom navigation bar.
/// </summary>
public partial class MainViewModel : ViewModelBase
{
    private readonly IHermesSyncService _syncService;

    public MainViewModel(TodoPageViewModel todoPage, SettingsPageViewModel settingsPage, IHermesSyncService syncService)
    {
        _syncService = syncService;
        TodoPage = todoPage;
        NavigationItems = new ObservableCollection<INavigationItem>
        {
            new NavigationItem("Todo List", AppIcons.Todo, todoPage),
            new NavigationItem("设置", AppIcons.Settings, settingsPage),
        };

        syncService.StatusChanged += (_, _) => Dispatcher.UIThread.Post(() =>
        {
            SyncStatusText = syncService.Status switch
            {
                SyncStatus.Idle => "空闲", SyncStatus.Syncing => "同步中", SyncStatus.Pulling => "拉取中",
                SyncStatus.Success => "已同步", SyncStatus.Error => "同步失败", SyncStatus.Skipped => "已跳过",
                _ => "空闲",
            };
            HasSyncError = syncService.Status == SyncStatus.Error;
            PendingSyncCount = syncService.PendingSyncCount;
        });

        _activeItem = NavigationItems[0];
        _activeIndex = 0;
    }

    public TodoPageViewModel TodoPage { get; }

    public ObservableCollection<INavigationItem> NavigationItems { get; }

    [ObservableProperty] private string _syncStatusText = "空闲";
    [ObservableProperty] private bool _hasSyncError;
    [ObservableProperty] private int _pendingSyncCount;

    [RelayCommand]
    private Task SyncNow() => _syncService.SyncNowAsync();

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

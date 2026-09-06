using System.Collections.ObjectModel;
using System.Threading.Tasks;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MashiruDaily.Abstracts;
using MashiruDaily.Assets;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.ViewModels;
using MashiruDaily.Core.ViewModels.Todo;
using MashiruDaily.Models;

namespace MashiruDaily.ViewModels;

/// <summary>
/// 根视图模型。暴露可用的导航条目与当前激活项。
/// 桌面侧边菜单（<c>SukiSideMenu</c>）与移动端底部导航栏消费同一批条目。
/// </summary>
public partial class MainViewModel : ViewModelBase
{
    private readonly IRemoteSyncService _syncService;

    [ObservableProperty]
    private string _syncStatusText = "空闲";

    [ObservableProperty]
    private bool _hasSyncError;

    [ObservableProperty]
    private int _pendingSyncCount;

    [ObservableProperty]
    private INavigationItem? _activeItem;

    [ObservableProperty]
    private int _activeIndex;

    public TodoPageViewModel TodoPage { get; }

    public ObservableCollection<INavigationItem> NavigationItems { get; }

    public MainViewModel(TodoPageViewModel todoPage,
        SettingsPageViewModel settingsPage,
        TalkViewModel talkPage,
        IRemoteSyncService syncService)
    {
        _syncService = syncService;
        TodoPage = todoPage;
        NavigationItems = new ObservableCollection<INavigationItem>
        {
            new NavigationItem("Todo List", AppIcons.Todo, todoPage),
            new NavigationItem("设置", AppIcons.Settings, settingsPage),
            new NavigationItem("聊天", AppIcons.Chat, talkPage),
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

    [RelayCommand]
    private Task SyncNow() => _syncService.SyncNowAsync();

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

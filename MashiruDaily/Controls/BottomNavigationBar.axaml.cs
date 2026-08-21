using System.Collections.Specialized;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;

namespace MashiruDaily.Controls;

/// <summary>
/// SukiUI 主题的移动端底部导航栏（标签页风格）。条目按等宽列排布；
/// 选中项以主色高亮、放大效果和底部指示器突出显示，并带按压反馈。
/// </summary>
public class BottomNavigationBar : ItemsControl
{
    public static readonly StyledProperty<int> SelectedIndexProperty =
        AvaloniaProperty.Register<BottomNavigationBar, int>(nameof(SelectedIndex), defaultValue: 0);

    private INotifyCollectionChanged? _subscribedItems;

    public int SelectedIndex
    {
        get => GetValue(SelectedIndexProperty);
        set => SetValue(SelectedIndexProperty, value);
    }

    public BottomNavigationBar()
    {
        SubscribeItemsCollection();
    }

    static BottomNavigationBar()
    {
        SelectedIndexProperty.Changed.AddClassHandler<BottomNavigationBar>((bar, _) => bar.OnSelectedIndexChanged());
        ItemsSourceProperty.Changed.AddClassHandler<BottomNavigationBar>((bar, _) => bar.OnItemsSourceChanged());
    }

    private void SubscribeItemsCollection()
    {
        if (_subscribedItems is not null)
            _subscribedItems.CollectionChanged -= OnItemsCollectionChanged;

        _subscribedItems = Items as INotifyCollectionChanged;

        if (_subscribedItems is not null)
            _subscribedItems.CollectionChanged += OnItemsCollectionChanged;
    }

    protected override bool NeedsContainerOverride(object? item, int index, out object? recycleKey)
    {
        recycleKey = null;
        return item is not BottomNavigationItem;
    }

    protected override Control CreateContainerForItemOverride(object? item, int index, object? recycleKey)
        => new BottomNavigationItem();

    protected override void PrepareContainerForItemOverride(Control container, object? item, int index)
    {
        base.PrepareContainerForItemOverride(container, item, index);

        if (container is BottomNavigationItem navigationItem)
        {
            navigationItem.Tapped -= OnItemTapped;
            navigationItem.Tapped += OnItemTapped;
            navigationItem.IsSelected = index == SelectedIndex;
        }
    }

    protected override void ClearContainerForItemOverride(Control container)
    {
        if (container is BottomNavigationItem navigationItem)
            navigationItem.Tapped -= OnItemTapped;

        base.ClearContainerForItemOverride(container);
    }

    private void OnItemsSourceChanged()
    {
        SubscribeItemsCollection();
        ClampSelection();
    }

    private void OnItemsCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        ClampSelection();
    }

    private void OnSelectedIndexChanged()
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (ContainerFromIndex(i) is BottomNavigationItem navigationItem)
                navigationItem.IsSelected = i == SelectedIndex;
        }
    }

    private void ClampSelection()
    {
        if (Items.Count == 0)
        {
            SelectedIndex = 0;
            return;
        }

        if (SelectedIndex < 0)
            SelectedIndex = 0;
        else if (SelectedIndex >= Items.Count)
            SelectedIndex = Items.Count - 1;
    }

    private void OnItemTapped(object? sender, TappedEventArgs e)
    {
        if (sender is not Control container)
            return;

        var index = IndexFromContainer(container);
        if (index >= 0 && index < Items.Count)
            SelectedIndex = index;
    }
}

using System.Collections.Specialized;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;

namespace MashiruDaily.Controls;

/// <summary>
/// A SukiUI-themed mobile bottom navigation bar in tab style. Items are laid out in equally sized columns;
/// the selected item is highlighted with the primary color, a scale-up effect, and a bottom indicator, with press feedback.
/// </summary>
public class BottomNavigationBar : ItemsControl
{
    public static readonly StyledProperty<int> SelectedIndexProperty =
        AvaloniaProperty.Register<BottomNavigationBar, int>(nameof(SelectedIndex), defaultValue: 0);

    public int SelectedIndex
    {
        get => GetValue(SelectedIndexProperty);
        set => SetValue(SelectedIndexProperty, value);
    }

    private INotifyCollectionChanged? _subscribedItems;

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

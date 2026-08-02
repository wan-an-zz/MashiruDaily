using System;
using System.Collections.Specialized;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Threading;

namespace MashiruDaily.Controls;

/// <summary>
/// A SukiUI-styled bottom navigation bar for mobile. Items are laid out in
/// equally sized columns; a soft "pill" indicator slides to the selected item
/// using SukiUI's standard easing/duration resources.
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

    private Border? _indicator;
    private INotifyCollectionChanged? _subscribedItems;

    public BottomNavigationBar()
    {
        SubscribeItemsCollection();
    }

    static BottomNavigationBar()
    {
        SelectedIndexProperty.Changed.AddClassHandler<BottomNavigationBar>((bar, _) => bar.OnSelectedIndexChanged());
        BoundsProperty.Changed.AddClassHandler<BottomNavigationBar>((bar, _) => bar.UpdateIndicator());
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

    protected override void OnApplyTemplate(TemplateAppliedEventArgs e)
    {
        base.OnApplyTemplate(e);
        _indicator = e.NameScope.Get<Border>("PART_Indicator");
        UpdateIndicator();
    }

    private void OnItemsSourceChanged()
    {
        SubscribeItemsCollection();
        ClampSelection();
        Dispatcher.UIThread.Post(UpdateIndicator);
    }

    private void OnItemsCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        ClampSelection();
        Dispatcher.UIThread.Post(UpdateIndicator);
    }

    private void OnSelectedIndexChanged()
    {
        for (var i = 0; i < Items.Count; i++)
        {
            if (ContainerFromIndex(i) is BottomNavigationItem navigationItem)
                navigationItem.IsSelected = i == SelectedIndex;
        }

        UpdateIndicator();
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

    private void UpdateIndicator()
    {
        var indicator = _indicator;
        if (indicator is null)
            return;

        var count = Items.Count;
        if (count == 0 || Bounds.Width <= 0)
        {
            indicator.IsVisible = count > 0;
            return;
        }

        var index = Math.Clamp(SelectedIndex, 0, count - 1);
        var columnWidth = Bounds.Width / count;
        var pillWidth = double.IsNaN(indicator.Width) ? 52 : indicator.Width;
        var x = index * columnWidth + (columnWidth - pillWidth) / 2d;

        indicator.RenderTransform = new TranslateTransform(x, 0);
        indicator.IsVisible = true;
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

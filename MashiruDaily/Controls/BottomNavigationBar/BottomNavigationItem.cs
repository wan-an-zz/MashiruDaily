using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;

namespace MashiruDaily.Controls;

/// <summary>
/// A single entry of the <see cref="BottomNavigationBar"/>. It hosts arbitrary
/// content (typically an icon + label) and exposes an <see cref="IsSelected"/>
/// state that is driven by the owning bar.
/// </summary>
public class BottomNavigationItem : ContentControl
{
    public static readonly StyledProperty<bool> IsSelectedProperty =
        AvaloniaProperty.Register<BottomNavigationItem, bool>(nameof(IsSelected));

    public bool IsSelected
    {
        get => GetValue(IsSelectedProperty);
        set => SetValue(IsSelectedProperty, value);
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);

        if (change.Property == IsSelectedProperty)
            PseudoClasses.Set(":selected", change.GetNewValue<bool>());
    }
}

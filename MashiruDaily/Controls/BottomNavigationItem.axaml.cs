using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;

namespace MashiruDaily.Controls;

/// <summary>
/// A single tab entry that hosts arbitrary content such as an icon and label, driven by the owning bar's
/// <see cref="IsSelected"/> state through selected and pressed pseudo-classes.
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

    protected override void OnPointerPressed(PointerPressedEventArgs e)
    {
        base.OnPointerPressed(e);
        if (e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
        {
            PseudoClasses.Set(":pressed", true);
            e.Pointer.Capture(this);
        }
    }

    protected override void OnPointerReleased(PointerReleasedEventArgs e)
    {
        base.OnPointerReleased(e);
        PseudoClasses.Set(":pressed", false);
        e.Pointer.Capture(null);
    }

    protected override void OnPointerCaptureLost(PointerCaptureLostEventArgs e)
    {
        base.OnPointerCaptureLost(e);
        PseudoClasses.Set(":pressed", false);
    }
}

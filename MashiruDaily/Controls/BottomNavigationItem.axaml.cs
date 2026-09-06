using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;

namespace MashiruDaily.Controls;

/// <summary>
/// 单个标签项，可承载图标、文字等任意内容；
/// 通过选中与按压伪类响应所属导航栏的 <see cref="IsSelected"/> 状态。
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

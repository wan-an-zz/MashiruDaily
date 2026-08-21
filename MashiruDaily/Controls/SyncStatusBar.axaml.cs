using System;
using System.Globalization;
using Avalonia.Controls;
using Avalonia.Data.Converters;

namespace MashiruDaily.Controls;

public partial class SyncStatusBar : UserControl
{
    public SyncStatusBar()
    {
        InitializeComponent();
    }
}

public sealed class PositiveIntToBoolConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value is int count && count > 0;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();
}

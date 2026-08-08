using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

/// <summary>一栏（待完成 / 已完成）：顶部标题 + 计数，下方为行列表区域。</summary>
internal sealed class TodoColumnView : View
{
    private readonly Label _header;

    public TodoColumnView(string header, int count)
    {
        CanFocus = true;
        _header = new Label
        {
            Text = $"{header} ({count})",
            X = 0,
            Y = 0,
        };
        Add(_header);
    }

    public void UpdateCount(int count)
    {
        var headerText = _header.Text ?? string.Empty;
        var name = headerText[..headerText.IndexOf('(')].Trim();
        _header.Text = $"{name} ({count})";
    }
}

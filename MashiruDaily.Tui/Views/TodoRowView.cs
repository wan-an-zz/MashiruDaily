using MashiruDaily.Core.ViewModels.Todo;
using Terminal.Gui.Configuration;
using Terminal.Gui.Drawing;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

/// <summary>一行待办：勾选框 + 标题。已完成行标题置灰。</summary>
internal sealed class TodoRowView : View
{
    private readonly Label _titleLabel;

    public TodoItemViewModel ViewModel { get; }

    public CheckBox CheckBoxControl { get; }

    public TodoRowView(TodoItemViewModel vm)
    {
        ViewModel = vm;
        CanFocus = false;

        CheckBoxControl = new CheckBox
        {
            X = 0,
            Y = 0,
            Width = 4,
            Value = vm.IsCompleted ? CheckState.Checked : CheckState.UnChecked,
            CanFocus = true,
        };

        _titleLabel = new Label
        {
            Text = vm.Title,
            X = Pos.Right(CheckBoxControl) + 1,
            Y = 0,
            Width = Dim.Fill(),
        };

        if (vm.IsCompleted)
        {
            Scheme baseScheme = SchemeManager.GetScheme(Schemes.Base);
            SchemeManager.AddScheme("muted", new Scheme { Normal = baseScheme.Disabled });
            _titleLabel.SchemeName = "muted";
        }

        Add(CheckBoxControl, _titleLabel);

        CheckBoxControl.ValueChanged += (_, _) => ViewModel.ToggleCommand.Execute(null);
    }

    public void SetSelected(bool selected)
    {
        _titleLabel.Text = selected ? $"> {ViewModel.Title}" : $"  {ViewModel.Title}";
    }
}

using MashiruDaily.ViewModels.Todo;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

/// <summary>一行待办：勾选框 + 标题 + [删除] 按钮。已完成行标题置灰。</summary>
internal sealed class TodoRowView : View
{
    public TodoItemViewModel ViewModel { get; }

    public CheckBox CheckBoxControl { get; }

    public Button DeleteButton { get; }

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

        Label titleLabel = new()
        {
            Text = vm.Title,
            X = Pos.Right(CheckBoxControl) + 1,
            Y = 0,
            Width = Dim.Fill(9),
        };

        DeleteButton = new Button
        {
            Text = "删除",
            X = Pos.AnchorEnd(),
            Y = 0,
            Width = 6,
            CanFocus = true,
        };

        Add(CheckBoxControl, titleLabel, DeleteButton);
    }
}

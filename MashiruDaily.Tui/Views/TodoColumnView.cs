using System.Collections.ObjectModel;
using System.Collections.Specialized;
using MashiruDaily.ViewModels.Todo;
using Terminal.Gui.App;
using Terminal.Gui.Input;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

/// <summary>
/// 一栏（待完成 / 已完成）：订阅 <see cref="ObservableCollection{T}"/> 变化并重建行。
/// 每个 <see cref="TodoItemViewModel"/> 对应一个 <see cref="TodoRowView"/>。
/// </summary>
internal sealed class TodoColumnView : View
{
    private readonly string _header;
    private readonly ObservableCollection<TodoItemViewModel> _source;
    private readonly Label _headerLabel;
    private readonly View _listArea;
    private int _selectedIndex;

    public TodoColumnView(string header, ObservableCollection<TodoItemViewModel> source)
    {
        _header = header;
        _source = source;
        CanFocus = true;

        _headerLabel = new Label { Text = $"{header} (0)", X = 0, Y = 0 };
        _listArea = new View
        {
            X = 0,
            Y = Pos.Bottom(_headerLabel) + 1,
            Width = Dim.Fill(),
            Height = Dim.Fill(),
        };
        Add(_headerLabel, _listArea);

        _source.CollectionChanged += OnSourceChanged;

        HasFocusChanged += (_, _) => HighlightSelected();
        
        KeyDown += (_, e) =>
        {
            if (e == Key.CursorUp)
            {
                MoveSelectionUp();
                e.Handled = true;
            }
            else if (e == Key.CursorDown)
            {
                MoveSelectionDown();
                e.Handled = true;
            }
            else if (e == Key.D || e == Key.Delete)
            {
                DeleteSelected();
                e.Handled = true;
            }
            else if (e == Key.Space)
            {
                ToggleSelected();
                e.Handled = true;
            }
        };

        Rebuild();
    }

    private void OnSourceChanged(object? sender, NotifyCollectionChangedEventArgs e) => Rebuild();

    private void Rebuild()
    {
        if (_source.Count == 0)
            _selectedIndex = 0;
        else if (_selectedIndex >= _source.Count)
            _selectedIndex = _source.Count - 1;

        _listArea.RemoveAll();

        int y = 0;
        foreach (var vm in _source)
        {
            var row = new TodoRowView(vm)
            {
                X = 0,
                Y = y,
                Width = Dim.Fill(),
                Height = 1,
            };
            row.SetSelected(y == _selectedIndex && HasFocus);
            _listArea.Add(row);
            y++;
        }

        _headerLabel.Text = $"{_header} ({_source.Count})";
    }

    private bool? MoveSelectionUp()
    {
        if (_selectedIndex > 0)
        {
            _selectedIndex--;
            HighlightSelected();
        }

        return true;
    }

    private bool? MoveSelectionDown()
    {
        if (_selectedIndex < _source.Count - 1)
        {
            _selectedIndex++;
            HighlightSelected();
        }

        return true;
    }

    private bool? ToggleSelected()
    {
        if (_selectedIndex >= 0 && _selectedIndex < _source.Count)
            _source[_selectedIndex].ToggleCommand.Execute(null);

        return true;
    }

    private bool? DeleteSelected()
    {
        if (_selectedIndex < 0 || _selectedIndex >= _source.Count)
            return true;

        var vm = _source[_selectedIndex];
        var result = MessageBox.Query(
            App!,
            "确认删除",
            $"确定删除「{vm.Title}」吗？",
            "取消",
            "删除");
        if (result == 1)
            vm.DeleteCommand.Execute(null);

        return true;
    }

    private void HighlightSelected()
    {
        var rows = _listArea.SubViews.ToArray();
        for (int i = 0; i < rows.Length; i++)
        {
            if (rows[i] is TodoRowView row)
                row.SetSelected(i == _selectedIndex && HasFocus);
        }
    }
}

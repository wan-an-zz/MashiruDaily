using System.Collections.ObjectModel;
using System.Collections.Specialized;
using MashiruDaily.ViewModels.Todo;
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
        Rebuild();
    }

    private void OnSourceChanged(object? sender, NotifyCollectionChangedEventArgs e) => Rebuild();

    private void Rebuild()
    {
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
            _listArea.Add(row);
            y++;
        }

        _headerLabel.Text = $"{_header} ({_source.Count})";
    }
}

using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.ViewModels.Todo;

/// <summary>
/// Wraps a single <see cref="TodoItem"/> for presentation. Keeps the editing
/// state (inline editing) and delegates all mutations to <see cref="ITodoService"/>.
/// </summary>
public partial class TodoItemViewModel : ViewModelBase
{
    private readonly ITodoService _service;

    public TodoItemViewModel(TodoItem item, ITodoService service)
    {
        _service = service;
        Item = item;
        _title = item.Title;
        _isCompleted = item.IsCompleted;
        _editText = item.Title;
    }

    /// <summary>The underlying data item.</summary>
    public TodoItem Item { get; }

    [ObservableProperty]
    private string _title;

    [ObservableProperty]
    private bool _isCompleted;

    [ObservableProperty]
    private bool _isEditing;

    [ObservableProperty]
    private string _editText;

    /// <summary>
    /// Refreshes display fields from the underlying item. Called after the
    /// service raises <see cref="ITodoService.Changed"/>.
    /// </summary>
    public void Sync()
    {
        Title = Item.Title;
        IsCompleted = Item.IsCompleted;
        if (!IsEditing)
            EditText = Item.Title;
    }

    [RelayCommand]
    private Task Toggle() => _service.ToggleAsync(Item);

    [RelayCommand]
    private Task Delete() => _service.RemoveAsync(Item);

    [RelayCommand]
    private void BeginEdit()
    {
        EditText = Title;
        IsEditing = true;
    }

    [RelayCommand]
    private async Task SaveEdit()
    {
        await _service.UpdateTitleAsync(Item, EditText);
        IsEditing = false;
    }

    [RelayCommand]
    private void CancelEdit()
    {
        EditText = Title;
        IsEditing = false;
    }
}

using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.ViewModels.Todo;

/// <summary>
/// 包装单个 <see cref="TodoItem"/> 用于展示。维护编辑状态（行内编辑），
/// 所有变更都委托给 <see cref="ITodoService"/>。
/// </summary>
public partial class TodoItemViewModel : ViewModelBase
{
    private readonly ITodoService _service;

    [ObservableProperty]
    private string _title;

    [ObservableProperty]
    private bool _isCompleted;

    [ObservableProperty]
    private bool _isEditing;

    [ObservableProperty]
    private string _editText;

    /// <summary>底层数据条目。</summary>
    public TodoItem Item { get; }

    public TodoItemViewModel(TodoItem item, ITodoService service)
    {
        _service = service;
        Item = item;
        _title = item.Title;
        _isCompleted = item.IsCompleted;
        _editText = item.Title;
    }

    /// <summary>
    /// 从底层条目刷新展示字段。服务触发 <see cref="ITodoService.Changed"/> 后调用。
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

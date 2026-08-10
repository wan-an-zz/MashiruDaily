using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.ViewModels.Todo;

/// <summary>
/// Page view-model for the Todo feature. Splits the todos coming from
/// <see cref="ITodoService"/> into a "pending" (待完成) and "completed"
/// (已完成) category and exposes the add/edit/delete/toggle commands.
/// </summary>
public partial class TodoPageViewModel : ViewModelBase
{
    private readonly ITodoService _service;
    private readonly Dictionary<TodoItem, TodoItemViewModel> _cache = new();

    public TodoPageViewModel(ITodoService service)
    {
        _service = service;
        _service.Changed += OnServiceChanged;
        OnServiceChanged(this, EventArgs.Empty);
    }

    public ObservableCollection<TodoItemViewModel> PendingTodos { get; } = new();

    public ObservableCollection<TodoItemViewModel> CompletedTodos { get; } = new();

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(AddCommand))]
    private string _newTodoTitle = string.Empty;

    [ObservableProperty]
    private int _pendingCount;

    [ObservableProperty]
    private int _completedCount;

    [ObservableProperty]
    private bool _hasPending;

    [ObservableProperty]
    private bool _hasCompleted;

    [RelayCommand(CanExecute = nameof(CanAdd))]
    private async Task Add()
    {
        var title = NewTodoTitle;
        NewTodoTitle = string.Empty;
        await _service.AddAsync(title);
    }

    private bool CanAdd() => !String.IsNullOrEmpty(NewTodoTitle);

    private void OnServiceChanged(object? sender, EventArgs e)
    {
        PendingTodos.Clear();
        CompletedTodos.Clear();

        foreach (var item in _service.Items)
        {
            if (!_cache.TryGetValue(item, out var viewModel))
            {
                viewModel = new TodoItemViewModel(item, _service);
                _cache[item] = viewModel;
            }

            viewModel.Sync();
            (item.IsCompleted ? CompletedTodos : PendingTodos).Add(viewModel);
        }

        PendingCount = PendingTodos.Count;
        CompletedCount = CompletedTodos.Count;
        HasPending = PendingCount > 0;
        HasCompleted = CompletedCount > 0;
    }
}

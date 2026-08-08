using MashiruDaily.ViewModels.Todo;
using Terminal.Gui.App;
using Terminal.Gui.Input;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

internal sealed class MainWindow : Runnable
{
    private readonly TodoPageViewModel _viewModel;
    private readonly TodoColumnView _pendingColumn;
    private readonly TodoColumnView _completedColumn;

    public MainWindow(TodoPageViewModel viewModel)
    {
        _viewModel = viewModel;
        Title = "MashiruDaily - Todo";

        // --- 左侧边栏 --------------------------------------------------------
        View sidebar = new()
        {
            Width = 16,
            Height = Dim.Fill(),
        };
        Label todoNav = new()
        {
            Text = "▶ Todo List",
            X = 1,
            Y = 1,
        };
        sidebar.Add(todoNav);

        // --- 右侧内容区 ------------------------------------------------------
        View content = new()
        {
            X = Pos.Right(sidebar),
            Y = 0,
            Width = Dim.Fill(),
            Height = Dim.Fill(),
        };

        Label title = new()
        {
            Text = "Todo",
            X = 1,
            Y = 1,
        };

        _pendingColumn = new TodoColumnView("待完成", 0)
        {
            X = 1,
            Y = Pos.Bottom(title) + 1,
            Width = Dim.Percent(50) - 2,
            Height = Dim.Fill() - 3,
        };

        _completedColumn = new TodoColumnView("已完成", 0)
        {
            X = Pos.Right(_pendingColumn) + 2,
            Y = Pos.Bottom(title) + 1,
            Width = Dim.Fill() - 3,
            Height = Dim.Fill() - 3,
        };

        content.Add(title, _pendingColumn, _completedColumn);

        // --- 状态栏（按键提示） ---------------------------------------------
        StatusBar status = new();
        status.Add(new Shortcut(Key.CursorUp, "选择", null));
        status.Add(new Shortcut(Key.CursorDown, "选择", null));
        status.Add(new Shortcut(Key.Space, "勾选", null));
        status.Add(new Shortcut(Key.D, "删除", null));
        status.Add(new Shortcut(Application.GetDefaultKey(Command.Quit), "退出", () => App?.RequestStop()));

        Add(sidebar, content, status);

        // 订阅视图模型变化，刷新计数
        _viewModel.PendingTodos.CollectionChanged += (_, _) => _pendingColumn.UpdateCount(_viewModel.PendingCount);
        _viewModel.CompletedTodos.CollectionChanged += (_, _) => _completedColumn.UpdateCount(_viewModel.CompletedCount);
    }
}

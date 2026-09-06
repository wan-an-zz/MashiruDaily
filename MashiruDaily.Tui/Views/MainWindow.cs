using MashiruDaily.Core.ViewModels;
using MashiruDaily.Core.ViewModels.Todo;
using Terminal.Gui.App;
using Terminal.Gui.Input;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

internal sealed class MainWindow : Runnable
{
    private readonly Label _todoNavLabel;

    private readonly Label _talkNavLabel;

    private readonly Label _settingsNavLabel;

    private readonly View _todoPage;

    private readonly AgentReactionView _talkPage;

    private readonly SettingsPageView _settingsPage;

    private readonly TodoColumnView _pendingColumn;

    private readonly TodoColumnView _completedColumn;

    private bool _showingTalk;

    private bool _showingSettings;

    public MainWindow(
        TodoPageViewModel todoViewModel,
        TalkViewModel talkViewModel,
        SettingsPageViewModel settingsViewModel)
    {
        Title = "MashiruDaily - Todo";

        // --- 左侧边栏 --------------------------------------------------------
        View sidebar = new()
        {
            Width = 18,
            Height = Dim.Fill(),
        };
        _todoNavLabel = new Label
        {
            Text = "▶ Todo List",
            X = 1,
            Y = 1,
        };
        _talkNavLabel = new Label
        {
            Text = "  Agent ",
            X = 1,
            Y = 2,
        };
        _settingsNavLabel = new Label
        {
            Text = "  设置",
            X = 1,
            Y = 3,
        };
        sidebar.Add(_todoNavLabel, _talkNavLabel, _settingsNavLabel);

        // --- 右侧内容区 ------------------------------------------------------
        // CanFocus 必须为 true：否则会切断从根到列的焦点链，初始焦点落到
        // StatusBar 上，列/行的 KeyDown 与按键全部收不到（仅应用级 Esc 有效）。
        View content = new()
        {
            CanFocus = true,
            X = Pos.Right(sidebar),
            Y = 0,
            Width = Dim.Fill(),
            Height = Dim.Fill(),
        };

        // --- 待办页面 --------------------------------------------------------
        _todoPage = new View
        {
            CanFocus = true,
            Width = Dim.Fill(),
            Height = Dim.Fill(),
        };

        Label title = new()
        {
            Text = "Todo",
            X = 1,
            Y = 1,
        };

        _pendingColumn = new TodoColumnView("待完成", todoViewModel.PendingTodos)
        {
            X = 1,
            Y = Pos.Bottom(title) + 1,
            Width = Dim.Percent(50) - 2,
            Height = Dim.Fill() - 3,
        };

        _completedColumn = new TodoColumnView("已完成", todoViewModel.CompletedTodos)
        {
            X = Pos.Right(_pendingColumn) + 2,
            Y = Pos.Bottom(title) + 1,
            Width = Dim.Fill() - 3,
            Height = Dim.Fill() - 3,
        };

        _todoPage.Add(title, _pendingColumn, _completedColumn);

        // --- Agent 页面 -----------------------------------------------------
        _talkPage = new AgentReactionView(talkViewModel)
        {
            Width = Dim.Fill(),
            Height = Dim.Fill(),
        };

        // --- 设置页面 -----------------------------------------------------
        _settingsPage = new SettingsPageView(settingsViewModel)
        {
            Width = Dim.Fill(),
            Height = Dim.Fill(),
        };

        content.Add(_todoPage, _talkPage, _settingsPage);

        // --- 键盘导航：Tab 在 待办 / Agent / 设置 页面间循环切换 ---------------
        KeyDown += (_, e) =>
        {
            if (e == Key.Tab)
            {
                CyclePage();
                e.Handled = true;
            }
        };

        // --- 状态栏（按键提示） ---------------------------------------------
        StatusBar status = new();
        status.Add(new Shortcut(Key.Tab, "切换页面", CyclePage));
        status.Add(new Shortcut(Key.CursorUp, "选择", null));
        status.Add(new Shortcut(Key.CursorDown, "选择", null));
        status.Add(new Shortcut(Key.Space, "勾选", null));
        status.Add(new Shortcut(Key.D, "删除", null));
        status.Add(new Shortcut(Application.GetDefaultKey(Command.Quit), "退出", () => App?.RequestStop()));

        Add(sidebar, content, status);

        // 初始显示待办页面，焦点放到待完成列。
        ShowTodoPage();
    }

    private void ShowTodoPage()
    {
        _showingTalk = false;
        _showingSettings = false;
        Title = "MashiruDaily - Todo";
        _todoPage.Visible = true;
        _talkPage.Visible = false;
        _settingsPage.Visible = false;
        _todoNavLabel.Text = "▶ Todo List";
        _talkNavLabel.Text = "  Agent ";
        _settingsNavLabel.Text = "  设置";
        _pendingColumn.SetFocus();
    }

    private void ShowTalkPage()
    {
        _showingTalk = true;
        _showingSettings = false;
        Title = "MashiruDaily - Agent";
        _todoPage.Visible = false;
        _talkPage.Visible = true;
        _settingsPage.Visible = false;
        _todoNavLabel.Text = "  Todo List";
        _talkNavLabel.Text = "▶ Agent ";
        _settingsNavLabel.Text = "  设置";
        _talkPage.FocusMessageView();
    }

    private void ShowSettingsPage()
    {
        _showingTalk = false;
        _showingSettings = true;
        Title = "MashiruDaily - 设置";
        _todoPage.Visible = false;
        _talkPage.Visible = false;
        _settingsPage.Visible = true;
        _todoNavLabel.Text = "  Todo List";
        _talkNavLabel.Text = "  Agent ";
        _settingsNavLabel.Text = "▶ 设置";
        _settingsPage.SetFocus();
    }

    private void CyclePage()
    {
        if (_showingTalk)
            ShowSettingsPage();
        else if (_showingSettings)
            ShowTodoPage();
        else
            ShowTalkPage();
    }
}

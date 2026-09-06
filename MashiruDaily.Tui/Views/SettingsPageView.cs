using System.ComponentModel;
using MashiruDaily.Core.ViewModels;
using Terminal.Gui.App;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

/// <summary>
/// 设置页面：展示当前远程同步配置与连接状态
/// </summary>
internal sealed class SettingsPageView : View
{
    private readonly SettingsPageViewModel _viewModel;

    private readonly Label _serverLabel;

    private readonly Label _hermesLabel;

    private readonly Label _syncEnabledLabel;

    private readonly Label _syncStatusLabel;

    private readonly Label _connectionStatusLabel;

    private readonly Button _testButton;

    private readonly Button _syncButton;

    public SettingsPageView(SettingsPageViewModel viewModel)
    {
        _viewModel = viewModel;
        CanFocus = true;

        Label title = new()
        {
            Text = "设置",
            X = 1,
            Y = 1,
        };

        _serverLabel = new Label
        {
            Text = $"服务器: {_viewModel.ServerBaseUrl}",
            X = 1,
            Y = 3,
        };

        _hermesLabel = new Label
        {
            Text = $"Hermes: {_viewModel.HermesBaseUrl}",
            X = 1,
            Y = 4,
        };

        _syncEnabledLabel = new Label
        {
            Text = $"同步: {(_viewModel.SyncEnabled ? "启用" : "禁用")}",
            X = 1,
            Y = 5,
        };

        _syncStatusLabel = new Label
        {
            Text = $"同步状态: {_viewModel.SyncStatusText}",
            X = 1,
            Y = 7,
        };

        _connectionStatusLabel = new Label
        {
            Text = $"连接状态: {_viewModel.TestResultText ?? "尚未测试"}",
            X = 1,
            Y = 8,
        };

        _testButton = new Button
        {
            Text = "测试连接",
            X = 1,
            Y = 10,
        };

        _syncButton = new Button
        {
            Text = "立即同步",
            X = Pos.Right(_testButton) + 2,
            Y = 10,
        };

        _testButton.Accepted += (_, _) => TestConnection();
        _syncButton.Accepted += (_, _) => SyncNow();

        Add(title, _serverLabel, _hermesLabel, _syncEnabledLabel, _syncStatusLabel, _connectionStatusLabel, _testButton, _syncButton);

        _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        Initialized += (_, _) => RefreshAll();
    }

    public void TestConnection() => _ = _viewModel.TestConnectionCommand.ExecuteAsync(null);

    public void SyncNow() => _ = _viewModel.SyncNowCommand.ExecuteAsync(null);

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (!IsInitialized)
            return;

        App?.Invoke(RefreshAll);
    }

    private void RefreshAll()
    {
        _serverLabel.Text = $"服务器: {_viewModel.ServerBaseUrl}";
        _hermesLabel.Text = $"Hermes: {_viewModel.HermesBaseUrl}";
        _syncEnabledLabel.Text = $"同步: {(_viewModel.SyncEnabled ? "启用" : "禁用")}";
        _syncStatusLabel.Text = $"同步状态: {_viewModel.SyncStatusText}";
        _connectionStatusLabel.Text = $"连接状态: {_viewModel.TestResultText ?? "尚未测试"}";
    }
}

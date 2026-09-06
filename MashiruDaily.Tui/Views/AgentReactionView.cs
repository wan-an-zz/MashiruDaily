// TextView 在 Terminal.Gui 2.4.17 中已标记过时（推荐 tui-cs/Editor 的 EditorView），
// 但后者是独立包；本项目继续使用随包自带的 TextView 做只读展示。
#pragma warning disable CS0618
using System.ComponentModel;
using MashiruDaily.Core.ViewModels;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;

namespace MashiruDaily.Tui.Views;

/// <summary>
/// Agent 反应页面：展示 <see cref="TalkViewModel.AgentMessage"/>，
/// 与桌面端共享同一个 <see cref="TalkViewModel"/> 数据来源。
/// </summary>
internal sealed class AgentReactionView : View
{
    private readonly TalkViewModel _viewModel;

    private readonly TextView _messageView;

    public AgentReactionView(TalkViewModel viewModel)
    {
        _viewModel = viewModel;
        CanFocus = true;

        Label title = new()
        {
            Text = "Agent 反应",
            X = 1,
            Y = 1,
        };

        _messageView = new TextView
        {
            X = 1,
            Y = Pos.Bottom(title) + 1,
            Width = Dim.Fill() - 2,
            Height = Dim.Fill() - 2,
            CanFocus = true,
            ReadOnly = true,
            Multiline = true,
            WordWrap = true,
            Text = _viewModel.AgentMessage,
        };

        Add(title, _messageView);

        _viewModel.PropertyChanged += OnViewModelPropertyChanged;
    }

    public void FocusMessageView()
    {
        _messageView.SetFocus();
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (!string.Equals(e.PropertyName, nameof(TalkViewModel.AgentMessage), StringComparison.Ordinal))
            return;

        // 视图挂载前构造函数已读取初始消息；未初始化或已销毁时不再刷新。
        if (!IsInitialized)
            return;

        void UpdateText()
        {
            _messageView.Text = _viewModel.AgentMessage;
        }

        App?.Invoke(UpdateText);
    }
}
#pragma warning restore CS0618

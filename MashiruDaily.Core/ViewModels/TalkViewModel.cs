using System.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Events;

namespace MashiruDaily.Core.ViewModels;

public partial class TalkViewModel : ViewModelBase
{
    private readonly SynchronizationContext? _uiContext;

    [ObservableProperty]
    private string _agentMessage = string.Empty;

    public TalkViewModel(IRemoteSyncService syncService)
    {
        _uiContext = SynchronizationContext.Current;
        syncService.GetMessageSuccessful += OnGetMessageSuccessful;
    }

    private void OnGetMessageSuccessful(object? sender, GetMessageSuccessfulEventArgs e)
    {
        if (_uiContext is null || _uiContext == SynchronizationContext.Current)
        {
            AgentMessage = e.Message;
            return;
        }

        _uiContext.Post(_ => AgentMessage = e.Message, null);
    }
}

using System;
using System.Threading;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Events;
using MashiruDaily.Core.ViewModels;
using Xunit;

namespace MashiruDaily.Tests;

public class TalkViewModelTests
{
    private sealed class FakeRemoteSyncService : IRemoteSyncService
    {
        public event EventHandler? StatusChanged
        {
            add { }
            remove { }
        }

        public event EventHandler<GetMessageSuccessfulEventArgs>? GetMessageSuccessful;

        public SyncStatus Status => SyncStatus.Idle;

        public string? LastError => null;

        public int PendingSyncCount => 0;

        public Task InitializeAsync() => Task.CompletedTask;

        public Task SyncNowAsync() => Task.CompletedTask;

        public Task FlushAsync() => Task.CompletedTask;

        public void RaiseGetMessageSuccessful(string message)
            => GetMessageSuccessful?.Invoke(this, new GetMessageSuccessfulEventArgs(message));
    }

    [Fact]
    public void GetMessageSuccessful_UpdatesAgentMessage_OnSameThread()
    {
        var syncService = new FakeRemoteSyncService();
        var originalContext = SynchronizationContext.Current;
        SynchronizationContext.SetSynchronizationContext(null);

        try
        {
            var viewModel = new TalkViewModel(syncService);

            syncService.RaiseGetMessageSuccessful("Agent 收到 Todo 更新。");

            Assert.Equal("Agent 收到 Todo 更新。", viewModel.AgentMessage);
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(originalContext);
        }
    }

    [Fact]
    public void GetMessageSuccessful_PostsToCapturedSynchronizationContext()
    {
        var syncService = new FakeRemoteSyncService();
        Exception? captured = null;
        var originalContext = SynchronizationContext.Current;
        var context = new SingleThreadSynchronizationContext();
        SynchronizationContext.SetSynchronizationContext(context);

        try
        {
            var viewModel = new TalkViewModel(syncService);

            var worker = new Thread(() => syncService.RaiseGetMessageSuccessful("异步消息"));
            worker.Start();
            worker.Join();

            context.RunPending();

            Assert.Equal("异步消息", viewModel.AgentMessage);
        }
        catch (Exception ex)
        {
            captured = ex;
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(originalContext);
        }

        if (captured is not null)
            throw captured;
    }

    private sealed class SingleThreadSynchronizationContext : SynchronizationContext
    {
        private readonly System.Collections.Concurrent.ConcurrentQueue<Action> _queue = new();

        public override void Post(SendOrPostCallback d, object? state)
            => _queue.Enqueue(() => d(state));

        public void RunPending()
        {
            while (_queue.TryDequeue(out var action))
                action();
        }
    }
}

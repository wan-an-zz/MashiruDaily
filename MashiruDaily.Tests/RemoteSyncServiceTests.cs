using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using MashiruDaily.Core.Abstracts;
using MashiruDaily.Core.Models;
using MashiruDaily.Core.Services;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace MashiruDaily.Tests;

/// <summary>
/// 手写的 HttpMessageHandler：记录每个请求并按脚本返回响应。
/// </summary>
public sealed class FakeHttpMessageHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, HttpResponseMessage> _responder;

    private readonly object _lock = new();

    private readonly List<RecordedRequest> _requests = new();

    public FakeHttpMessageHandler(Func<HttpRequestMessage, HttpResponseMessage> responder)
    {
        _responder = responder;
    }

    public IReadOnlyList<RecordedRequest> Requests
    {
        get
        {
            lock (_lock)
            {
                return _requests.ToList();
            }
        }
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = request.Content is null
            ? null
            : request.Content.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult();

        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var header in request.Headers)
            headers[header.Key] = string.Join(",", header.Value);
        if (request.Content?.Headers is not null)
        {
            foreach (var header in request.Content.Headers)
                headers[header.Key] = string.Join(",", header.Value);
        }

        var recorded = new RecordedRequest(request.Method, request.RequestUri!, headers, body);
        lock (_lock)
        {
            _requests.Add(recorded);
        }

        return Task.FromResult(_responder(request));
    }
}

public sealed record RecordedRequest(
    HttpMethod Method,
    Uri Uri,
    IReadOnlyDictionary<string, string> Headers,
    string? Body);

/// <summary>
/// 始终以给定异常使请求失败的 HttpMessageHandler。
/// </summary>
public sealed class ThrowingHttpMessageHandler : HttpMessageHandler
{
    private readonly Exception _exception;

    public ThrowingHttpMessageHandler(Exception exception) => _exception = exception;

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
        => Task.FromException<HttpResponseMessage>(_exception);
}

public class RemoteSyncServiceTests : IDisposable
{
    private const string ServerUpdatedAt = "2026-08-10T17:00:00+08:00";

    private const string OlderUpdatedAt = "2026-08-10T16:00:00+08:00";

    private const string LaterUpdatedAt = "2026-08-10T18:00:00+08:00";

    private const string ServerUpdatedAtNormalized = "2026-08-10T17:00:00.0000000+08:00";

    private readonly string _dir;

    public RemoteSyncServiceTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "MashiruDaily.Tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
            Directory.Delete(_dir, recursive: true);
    }

    private static async Task WaitUntilAsync(
        Func<bool> predicate, string? message = null, int timeoutMs = 8000)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (!predicate())
        {
            if (DateTime.UtcNow >= deadline)
                throw new TimeoutException(message ?? "Timed out waiting for condition.");
            await Task.Delay(10);
        }
    }

    private static HttpResponseMessage JsonResponse(HttpStatusCode status, string json) =>
        new(status) { Content = new StringContent(json, Encoding.UTF8, "application/json") };

    private static HttpResponseMessage OkPushResponse() =>
        JsonResponse(HttpStatusCode.OK, "{\"success\":true,\"error_ids\":[],\"success_ids\":[]}");

    private static RemoteServerSettings SyncSettings() => new()
    {
        SyncEnabled = true,
        HermesBaseUrl = "http://hermes.test",
        WebhookRouteName = "todo-sync",
        WebhookSecret = "test-secret",
        ServerBaseUrl = "http://server.test:8123",
        MaxRetryAttempts = 0,
        TimeoutSeconds = 5,
        LastSyncedAt = ServerUpdatedAt,
    };

    private static FakeHttpMessageHandler CreateMetaHandler(
        string? metaUpdatedAt = null,
        Func<HttpRequestMessage, HttpResponseMessage>? postResponder = null,
        string? todoJson = null)
    {
        var updatedAt = metaUpdatedAt ?? ServerUpdatedAt;
        return new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return postResponder?.Invoke(request) ?? OkPushResponse();

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK,
                    $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{updatedAt}\"}}");

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK, todoJson ?? "[]");

            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });
    }

    private async Task<(TodoService TodoService, RemoteServerSettingsService SettingsRepo, RemoteSyncService SyncService, HttpMessageHandler Handler)>
        CreateHarnessAsync(HttpMessageHandler handler, RemoteServerSettings? settings = null, params TodoItem[] seed)
        => await CreateHarnessCoreAsync(handler, settings, null, false, seed);

    private async Task<(TodoService TodoService, RemoteServerSettingsService SettingsRepo, RemoteSyncService SyncService, HttpMessageHandler Handler)>
        CreateWebhookHarnessAsync(
            HttpMessageHandler handler,
            RemoteServerSettings? settings = null,
            TimeSpan? agentReactionPollInterval = null,
            params TodoItem[] seed)
        => await CreateHarnessCoreAsync(handler, settings, agentReactionPollInterval, true, seed);

    private async Task<(TodoService TodoService, RemoteServerSettingsService SettingsRepo, RemoteSyncService SyncService, HttpMessageHandler Handler)>
        CreateHarnessCoreAsync(
            HttpMessageHandler handler,
            RemoteServerSettings? settings,
            TimeSpan? agentReactionPollInterval,
            bool webhookReactionEnabled,
            params TodoItem[] seed)
    {
        var todoRepo = new TodoRepoService(NullLogger<TodoRepoService>.Instance, _dir);
        await todoRepo.SaveAsync(seed);

        var todoService = new TodoService(todoRepo, NullLogger<TodoService>.Instance);
        await todoService.InitializeAsync();

        var settingsRepo = new RemoteServerSettingsService(NullLogger<RemoteServerSettingsService>.Instance, _dir);
        await settingsRepo.SaveAsync(settings ?? SyncSettings());

        var httpClient = new HttpClient(handler);
        var syncService = new RemoteSyncService(
            todoService,
            settingsRepo,
            NullLogger<RemoteSyncService>.Instance,
            httpClient,
            agentReactionPollInterval,
            webhookReactionEnabled);

        return (todoService, settingsRepo, syncService, handler);
    }

    private static string EventTypeOf(RecordedRequest request, int index = 0)
    {
        using var doc = JsonDocument.Parse(request.Body!);
        return doc.RootElement
            .GetProperty("events")[index]
            .GetProperty("event_type")
            .GetString()!;
    }

    private static void AssertPushContract(
        RecordedRequest request,
        params string[] expectedEventTypes)
    {
        Assert.EndsWith("/api/update", request.Uri.AbsolutePath);
        Assert.True(request.Headers.TryGetValue("X-Webhook-Timestamp", out var timestamp));
        Assert.True(long.TryParse(timestamp, out _), "X-Webhook-Timestamp 必须是 Unix 秒数字符串。");

        Assert.True(request.Headers.TryGetValue("X-Webhook-Signature-V2", out var signature));
        var expectedSignature = HermesWebhookSigner.ComputeSignature("test-secret", timestamp, request.Body!);
        Assert.Equal(expectedSignature, signature);

        Assert.True(request.Headers.TryGetValue("X-Request-ID", out var requestId));
        Assert.True(Guid.TryParse(requestId, out _));

        using var doc = JsonDocument.Parse(request.Body!);
        var root = doc.RootElement;
        Assert.Equal(JsonValueKind.Object, root.ValueKind);
        Assert.Equal("update", root.GetProperty("event_type").GetString());
        Assert.True(root.TryGetProperty("updated_at", out var updatedAt));
        Assert.False(string.IsNullOrWhiteSpace(updatedAt.GetString()));

        var events = root.GetProperty("events");
        Assert.Equal(expectedEventTypes.Length, events.GetArrayLength());
        for (var i = 0; i < expectedEventTypes.Length; i++)
        {
            var envelope = events[i];
            Assert.Equal(expectedEventTypes[i], envelope.GetProperty("event_type").GetString());
            Assert.True(envelope.TryGetProperty("timestamp", out _));
            Assert.False(envelope.TryGetProperty("event_id", out _));
            Assert.False(envelope.TryGetProperty("client_id", out _));

            var payload = envelope.GetProperty("payload");
            Assert.True(payload.TryGetProperty("id", out _));
            Assert.True(payload.TryGetProperty("title", out _));
            Assert.True(payload.TryGetProperty("is_completed", out _));
            Assert.True(payload.TryGetProperty("created_at", out _));
            Assert.True(payload.TryGetProperty("completed_at", out _));
            Assert.False(payload.TryGetProperty("has_synced", out _));
        }
    }

    private static void TriggerTick(RemoteSyncService syncService)
    {
        var method = typeof(RemoteSyncService).GetMethod(
            "OnTick", BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("未找到 RemoteSyncService.OnTick。");
        method.Invoke(syncService, new object?[] { null });
    }

    [Fact]
    public async Task InitializeAsync_ServerNewer_PullsReplacesAndPersistsLastSyncedAt()
    {
        var local = new TodoItem { Title = "local", HasSynced = true };
        var settings = SyncSettings();
        settings.LastSyncedAt = OlderUpdatedAt;

        var todoJson = "[{\"id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\"," +
                       "\"title\":\"Pulled\",\"is_completed\":false," +
                       "\"created_at\":\"2026-08-10T18:00:00+08:00\",\"completed_at\":null}]";
        var handler = CreateMetaHandler(LaterUpdatedAt, todoJson: todoJson);
        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        var item = Assert.Single(todoService.Items);
        Assert.Equal("Pulled", item.Title);
        Assert.True(todoService.Items.All(x => x.HasSynced));

        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal("2026-08-10T18:00:00.0000000+08:00", reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task InitializeAsync_ServerNotNewer_PushesPendingToApiUpdate()
    {
        var local = new TodoItem { Title = "pending", HasSynced = false };
        var handler = CreateMetaHandler();
        var harness = await CreateHarnessAsync(handler, SyncSettings(), local);
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        var post = Assert.Single(handler.Requests, r => r.Method == HttpMethod.Post);
        AssertPushContract(post, "todo_updated");

        using var doc = JsonDocument.Parse(post.Body!);
        var payload = doc.RootElement.GetProperty("events")[0].GetProperty("payload");
        Assert.Equal(local.Id, payload.GetProperty("id").GetGuid());
        Assert.Equal("pending", payload.GetProperty("title").GetString());
        Assert.False(payload.GetProperty("is_completed").GetBoolean());

        Assert.True(todoService.Items.Single().HasSynced);

        // 服务端会用本次 updated_at 刷新 todo-meta.json，客户端同步推进 LastSyncedAt。
        var pushedUpdatedAt = doc.RootElement.GetProperty("updated_at").GetString();
        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal(pushedUpdatedAt, reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task Mutations_ProduceAllChangeEvents_WithSnapshots()
    {
        var handler = CreateMetaHandler();
        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await todoService.AddAsync("Task");
        TriggerTick(syncService);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 1);
        Assert.Equal("todo_added", EventTypeOf(handler.Requests.Single(r => r.Method == HttpMethod.Post)));

        var item = todoService.Items.Single();
        await todoService.ToggleAsync(item);
        TriggerTick(syncService);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 2);
        Assert.Equal("todo_completed", EventTypeOf(handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(1)));

        await todoService.ToggleAsync(item);
        TriggerTick(syncService);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 3);
        Assert.Equal("todo_reopened", EventTypeOf(handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(2)));

        await todoService.UpdateTitleAsync(item, "Renamed");
        TriggerTick(syncService);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 4);
        Assert.Equal("todo_updated", EventTypeOf(handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(3)));

        await todoService.RemoveAsync(item);
        TriggerTick(syncService);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 5);

        var deletedRequest = handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(4);
        Assert.Equal("todo_deleted", EventTypeOf(deletedRequest));
        using var doc = JsonDocument.Parse(deletedRequest.Body!);
        var payload = doc.RootElement.GetProperty("events")[0].GetProperty("payload");
        Assert.Equal(item.Id, payload.GetProperty("id").GetGuid());
        Assert.Equal("Renamed", payload.GetProperty("title").GetString());
    }

    [Fact]
    public async Task Http500_ParsesPartialSuccess_AndDoesNotRetry()
    {
        var okId = Guid.NewGuid();
        var errorId = Guid.NewGuid();
        var settings = SyncSettings();
        settings.MaxRetryAttempts = 2;

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
            {
                return JsonResponse(HttpStatusCode.InternalServerError,
                    $"{{\"success\":false,\"error_ids\":[\"{errorId}\"],\"success_ids\":[\"{okId}\"]}}");
            }

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings,
            new TodoItem { Id = okId, Title = "ok", HasSynced = false },
            new TodoItem { Id = errorId, Title = "err", HasSynced = false });
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        var post = Assert.Single(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.Equal(SyncStatus.Error, syncService.Status);
        Assert.True(todoService.Items.Single(x => x.Id == okId).HasSynced);
        Assert.False(todoService.Items.Single(x => x.Id == errorId).HasSynced);
        Assert.Equal(1, syncService.PendingSyncCount);

        // 部分成功时服务端会为成功部分刷新 updated_at，客户端也推进 LastSyncedAt。
        using var doc = JsonDocument.Parse(post.Body!);
        var pushedUpdatedAt = doc.RootElement.GetProperty("updated_at").GetString();
        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal(pushedUpdatedAt, reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task NetworkError_ExhaustsAttempts_KeepsPending()
    {
        var settings = SyncSettings();
        settings.MaxRetryAttempts = 0;

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                throw new HttpRequestException("connection refused");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings);
        var (todoService, _, syncService, _) = harness;
        await syncService.InitializeAsync();

        await todoService.AddAsync("Will fail");
        TriggerTick(syncService);

        await WaitUntilAsync(
            () => syncService.Status == SyncStatus.Error && !string.IsNullOrEmpty(syncService.LastError),
            "网络失败后未进入 Error 状态。");

        Assert.False(todoService.Items.Single().HasSynced);
        Assert.Equal(1, syncService.PendingSyncCount);
    }

    [Fact]
    public async Task HttpError_ExhaustsRetryAttempts_KeepsPending()
    {
        var settings = SyncSettings();
        settings.MaxRetryAttempts = 1;

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.BadRequest, "{\"success\":false}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings);
        var (todoService, _, syncService, _) = harness;
        await syncService.InitializeAsync();

        await todoService.AddAsync("Will fail");
        TriggerTick(syncService);

        await WaitUntilAsync(
            () => syncService.Status == SyncStatus.Error && handler.Requests.Count(r => r.Method == HttpMethod.Post) == 2,
            "HTTP 失败后未按重试次数耗尽进入 Error。");

        Assert.False(todoService.Items.Single().HasSynced);
        Assert.Equal(1, syncService.PendingSyncCount);
    }

    [Fact]
    public async Task SyncNowAsync_ResendsPreviouslyFailedPendingItems()
    {
        var itemId = Guid.NewGuid();
        var postCount = 0;
        var settings = SyncSettings();
        settings.MaxRetryAttempts = 0;

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
            {
                postCount++;
                return postCount == 1
                    ? JsonResponse(HttpStatusCode.InternalServerError,
                        $"{{\"success\":false,\"error_ids\":[\"{itemId}\"],\"success_ids\":[]}}")
                    : OkPushResponse();
            }

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings,
            new TodoItem { Id = itemId, Title = "Retry me", HasSynced = false });
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();
        Assert.Equal(SyncStatus.Error, syncService.Status);
        Assert.False(todoService.Items.Single().HasSynced);

        await syncService.SyncNowAsync();

        Assert.True(todoService.Items.Single().HasSynced);
        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.Equal(2, handler.Requests.Count(r => r.Method == HttpMethod.Post));
    }

    [Fact]
    public async Task FlushAsync_PushesPendingAsUpdated()
    {
        var handler = CreateMetaHandler();
        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;
        await syncService.InitializeAsync();

        await todoService.AddAsync("Flush me");
        await syncService.FlushAsync();

        var post = Assert.Single(handler.Requests, r => r.Method == HttpMethod.Post);
        AssertPushContract(post, "todo_updated");
        Assert.True(todoService.Items.Single().HasSynced);
    }

    [Fact]
    public async Task InitializeAsync_SplitsLargeBatchIntoFifteenPerPost()
    {
        var seed = Enumerable.Range(1, 16)
            .Select(i => new TodoItem { Title = $"T{i}", HasSynced = false })
            .ToArray();
        var handler = CreateMetaHandler();
        var harness = await CreateHarnessAsync(handler, SyncSettings(), seed);
        var (_, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        var posts = handler.Requests.Where(r => r.Method == HttpMethod.Post).ToList();
        Assert.Equal(2, posts.Count);

        using var firstDoc = JsonDocument.Parse(posts[0].Body!);
        using var secondDoc = JsonDocument.Parse(posts[1].Body!);
        Assert.Equal(15, firstDoc.RootElement.GetProperty("events").GetArrayLength());
        Assert.Equal(1, secondDoc.RootElement.GetProperty("events").GetArrayLength());
        Assert.All(firstDoc.RootElement.GetProperty("events").EnumerateArray(),
            e => Assert.Equal("todo_updated", e.GetProperty("event_type").GetString()));

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.Equal(0, syncService.PendingSyncCount);
    }

    [Fact]
    public async Task InitializeAsync_MissingUpdatedAt_MetaError_NoHttpMutation()
    {
        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return OkPushResponse();
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, "{\"date\":\"2026-08-10\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK, "[]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler);
        var (_, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Error, syncService.Status);
        Assert.Contains("updated_at", syncService.LastError);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.DoesNotContain(handler.Requests, r => r.Uri.AbsolutePath.EndsWith("/api/todo"));
    }

    [Fact]
    public async Task InitializeAsync_SyncDisabled_MakesNoHttpRequests()
    {
        var settings = SyncSettings();
        settings.SyncEnabled = false;

        var handler = new FakeHttpMessageHandler(_ => new HttpResponseMessage(HttpStatusCode.NotFound));
        var harness = await CreateHarnessAsync(handler, settings);
        var (_, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Empty(handler.Requests);
        Assert.Equal(SyncStatus.Idle, syncService.Status);
    }
    [Fact]
    public async Task WebhookReaction_AfterSuccess_PushesToHermesAndPollsServerMessages()
    {
        var settings = SyncSettings();

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post &&
                request.RequestUri!.AbsolutePath.EndsWith("/api/update"))
                return OkPushResponse();

            if (request.Method == HttpMethod.Post &&
                request.RequestUri!.AbsolutePath.EndsWith("/webhooks/todo-sync"))
                return new HttpResponseMessage(HttpStatusCode.OK);

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK,
                    $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/messages"))
                return JsonResponse(HttpStatusCode.OK,
                    "{\"exist\":true,\"text\":\"Agent消息\",\"time\":\"2026-08-10T18:00:00+08:00\"}");

            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateWebhookHarnessAsync(
            handler, settings, TimeSpan.FromMilliseconds(20),
            new TodoItem { Title = "任务1", HasSynced = false });
        var (_, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await WaitUntilAsync(() =>
            handler.Requests.Any(r => r.Method == HttpMethod.Post &&
                r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync")),
            "未收到 Hermes Webhook POST");

        await WaitUntilAsync(() =>
            handler.Requests.Any(r => r.Method == HttpMethod.Get &&
                r.Uri!.AbsolutePath.EndsWith("/api/messages")),
            "未轮询 /api/messages");

        await WaitUntilAsync(() => syncService.Status == SyncStatus.Success,
            "拉取到 Agent 消息后未进入 Success");

        var serverPost = handler.Requests.Single(r =>
            r.Method == HttpMethod.Post && r.Uri!.AbsolutePath.EndsWith("/api/update"));
        AssertPushContract(serverPost, "todo_updated");

        var webhookPost = handler.Requests.Single(r =>
            r.Method == HttpMethod.Post && r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync"));
        Assert.EndsWith("/webhooks/todo-sync", webhookPost.Uri.AbsolutePath);
        Assert.True(webhookPost.Headers.ContainsKey("X-Webhook-Timestamp"));
        Assert.True(webhookPost.Headers.ContainsKey("X-Webhook-Signature-V2"));
        Assert.True(webhookPost.Headers.ContainsKey("X-Request-ID"));

        using var doc = JsonDocument.Parse(webhookPost.Body!);
        Assert.Equal("update", doc.RootElement.GetProperty("event_type").GetString());
        Assert.Equal(1, doc.RootElement.GetProperty("events").GetArrayLength());

        Assert.DoesNotContain(handler.Requests, r =>
            r.Method == HttpMethod.Get && r.Uri!.AbsolutePath.Contains("/webhooks/"));

        syncService.Dispose();
    }

    [Fact]
    public async Task WebhookReaction_PartialSuccess_SendsOnlySuccessfulTodoToHermes()
    {
        var okId = Guid.NewGuid();
        var errId = Guid.NewGuid();

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post &&
                request.RequestUri!.AbsolutePath.EndsWith("/api/update"))
            {
                return JsonResponse(HttpStatusCode.InternalServerError,
                    $"{{\"success\":false,\"error_ids\":[\"{errId}\"],\"success_ids\":[\"{okId}\"]}}");
            }

            if (request.Method == HttpMethod.Post &&
                request.RequestUri!.AbsolutePath.EndsWith("/webhooks/todo-sync"))
                return new HttpResponseMessage(HttpStatusCode.OK);

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK,
                    $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");

            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateWebhookHarnessAsync(
            handler, SyncSettings(), TimeSpan.FromMilliseconds(20),
            new TodoItem { Id = okId, Title = "成功项", HasSynced = false },
            new TodoItem { Id = errId, Title = "失败项", HasSynced = false });
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await WaitUntilAsync(() =>
            handler.Requests.Any(r => r.Method == HttpMethod.Post &&
                r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync")),
            "部分成功时未收到 Hermes Webhook POST");

        var webhookPost = handler.Requests.First(r =>
            r.Method == HttpMethod.Post && r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync"));

        using var doc = JsonDocument.Parse(webhookPost.Body!);
        var events = doc.RootElement.GetProperty("events");
        Assert.Equal(1, events.GetArrayLength());
        Assert.Equal(okId, events[0].GetProperty("payload").GetProperty("id").GetGuid());
        Assert.DoesNotContain(events.EnumerateArray(), e =>
            e.GetProperty("payload").GetProperty("id").GetGuid() == errId);

        Assert.True(todoService.Items.Single(x => x.Id == okId).HasSynced);
        Assert.False(todoService.Items.Single(x => x.Id == errId).HasSynced);

        syncService.Dispose();
    }

    [Fact]
    public async Task WebhookReaction_Disabled_DoesNotSendHermesRequest()
    {
        var handler = CreateMetaHandler();
        var harness = await CreateHarnessAsync(
            handler, SyncSettings(),
            new TodoItem { Title = "任务1", HasSynced = false });
        var (_, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        var post = Assert.Single(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.EndsWith("/api/update", post.Uri.AbsolutePath);
        Assert.DoesNotContain(handler.Requests, r =>
            r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync"));
    }

    [Fact]
    public async Task WebhookReaction_WebhookFailure_DoesNotBlockSync()
    {
        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post &&
                request.RequestUri!.AbsolutePath.EndsWith("/api/update"))
                return OkPushResponse();

            if (request.Method == HttpMethod.Post &&
                request.RequestUri!.AbsolutePath.EndsWith("/webhooks/todo-sync"))
                return new HttpResponseMessage(HttpStatusCode.InternalServerError);

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK,
                    $"{{\"date\":\"2026-08-10\",\"updated_at\":\"{ServerUpdatedAt}\"}}");

            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateWebhookHarnessAsync(
            handler, SyncSettings(), TimeSpan.FromMilliseconds(20),
            new TodoItem { Title = "任务1", HasSynced = false });
        var (_, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await WaitUntilAsync(() =>
            handler.Requests.Any(r => r.Method == HttpMethod.Post &&
                r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync")),
            "Webhook 失败时未发出 Hermes 请求");

        Assert.Contains(handler.Requests, r =>
            r.Method == HttpMethod.Post && r.Uri!.AbsolutePath.EndsWith("/webhooks/todo-sync"));

        syncService.Dispose();
    }
}

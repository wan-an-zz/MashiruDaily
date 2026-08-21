using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
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
    private const string ServerCreatedAt = "2026-08-10T17:00:00+08:00";

    private const string OlderCreatedAt = "2026-08-10T16:00:00+08:00";

    private const string LaterCreatedAt = "2026-08-10T18:00:00+08:00";

    private const string ServerCreatedAtNormalized = "2026-08-10T17:00:00.0000000+08:00";

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
        Func<bool> predicate, string? message = null, int timeoutMs = 5000)
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

    private static RemoteServerSettings SyncSettings() => new()
    {
        SyncEnabled = true,
        HermesBaseUrl = "http://hermes.test",
        WebhookRouteName = "todo-sync",
        WebhookSecret = "test-secret",
        ServerBaseUrl = "http://hermes.test",
        MaxRetryAttempts = 2,
        TimeoutSeconds = 5,
        LastSyncedAt = ServerCreatedAt,
    };

    private static FakeHttpMessageHandler CreateWebhookHandler(HttpStatusCode postStatus) =>
        new(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(postStatus, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

    private async Task<(TodoService TodoService, RemoteServerSettingsService SettingsRepo, RemoteSyncService SyncService, HttpMessageHandler Handler)>
        CreateHarnessAsync(HttpMessageHandler handler, RemoteServerSettings? settings = null, params TodoItem[] seed)
    {
        var todoRepo = new TodoRepoService(NullLogger<TodoRepoService>.Instance, _dir);
        await todoRepo.SaveAsync(seed);

        var todoService = new TodoService(todoRepo, NullLogger<TodoService>.Instance);
        await todoService.InitializeAsync();

        var settingsRepo = new RemoteServerSettingsService(NullLogger<RemoteServerSettingsService>.Instance, _dir);
        await settingsRepo.SaveAsync(settings ?? SyncSettings());

        var httpClient = new HttpClient(handler);
        var syncService = new RemoteSyncService(
            todoService, settingsRepo, NullLogger<RemoteSyncService>.Instance, httpClient);

        return (todoService, settingsRepo, syncService, handler);
    }

    private static string EventTypeOf(RecordedRequest request, int index = 0)
    {
        using var doc = JsonDocument.Parse(request.Body!);
        return doc.RootElement[index].GetProperty("event_type").GetString()!;
    }

    [Fact]
    public async Task AddAsync_PushesTodoAddedWebhook_WithSignedHeaders_AndMarksSynced()
    {
        var handler = CreateWebhookHandler(HttpStatusCode.Accepted);
        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await todoService.AddAsync("Buy milk");
        var item = todoService.Items.Single();

        await WaitUntilAsync(
            () => item.HasSynced && syncService.Status == SyncStatus.Success && syncService.PendingSyncCount == 0,
            "AddAsync webhook was not processed to success.");

        var posts = handler.Requests.Where(r => r.Method == HttpMethod.Post).ToList();
        var request = Assert.Single(posts);

        Assert.EndsWith("/webhooks/todo-sync", request.Uri.AbsolutePath);

        Assert.True(request.Headers.TryGetValue("X-Webhook-Timestamp", out var timestamp));
        Assert.True(long.TryParse(timestamp, out _), "X-Webhook-Timestamp must be a numeric Unix timestamp.");

        Assert.True(request.Headers.TryGetValue("X-Webhook-Signature-V2", out var signature));
        var expectedSignature = HermesWebhookSigner.ComputeSignature("test-secret", timestamp, request.Body!);
        Assert.Equal(expectedSignature, signature);

        Assert.True(request.Headers.TryGetValue("X-Request-ID", out var requestId));
        Assert.True(Guid.TryParse(requestId, out _));

        using var doc = JsonDocument.Parse(request.Body!);
        var root = doc.RootElement;
        Assert.Equal(JsonValueKind.Array, root.ValueKind);
        var envelope = Assert.Single(root.EnumerateArray());
        Assert.Equal("todo_added", envelope.GetProperty("event_type").GetString());
        Assert.True(envelope.TryGetProperty("event_id", out var eventIdElement));
        Assert.True(Guid.TryParse(eventIdElement.GetString(), out _));
        Assert.True(envelope.TryGetProperty("client_id", out var clientIdElement));
        Assert.True(Guid.TryParse(clientIdElement.GetString(), out _));
        Assert.Equal(item.Id, envelope.GetProperty("payload").GetProperty("id").GetGuid());
        Assert.Equal("Buy milk", envelope.GetProperty("payload").GetProperty("title").GetString());
        Assert.False(envelope.GetProperty("payload").GetProperty("is_completed").GetBoolean());
        Assert.False(envelope.GetProperty("payload").TryGetProperty("has_synced", out _));
    }

    [Fact]
    public async Task Http500_KeepsItemPending_AndExhaustsRetryAttempts()
    {
        var handler = CreateWebhookHandler(HttpStatusCode.InternalServerError);
        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await todoService.AddAsync("Will fail");
        var item = todoService.Items.Single();

        await WaitUntilAsync(
            () => syncService.Status == SyncStatus.Error && !string.IsNullOrEmpty(syncService.LastError),
            "Webhook failure did not surface an Error status.");

        Assert.False(item.HasSynced);
        Assert.Equal(1, syncService.PendingSyncCount);
        Assert.Equal(3, handler.Requests.Count(r => r.Method == HttpMethod.Post));
    }

    [Fact]
    public async Task HttpRequestException_ResultsInError_WithoutUnhandledException()
    {
        var handler = new ThrowingHttpMessageHandler(new HttpRequestException("connection refused"));
        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await todoService.AddAsync("Will throw");
        var item = todoService.Items.Single();

        await WaitUntilAsync(
            () => syncService.Status == SyncStatus.Error && !string.IsNullOrEmpty(syncService.LastError),
            "Network failure did not surface an Error status.");

        Assert.False(item.HasSynced);
    }

    [Fact]
    public async Task SyncNowAsync_ResendsPreviouslyFailedPendingItems()
    {
        var postCount = 0;
        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
            {
                postCount++;
                return postCount <= 3
                    ? new HttpResponseMessage(HttpStatusCode.InternalServerError)
                    : JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            }

            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await todoService.AddAsync("Retry me");
        var item = todoService.Items.Single();

        await WaitUntilAsync(
            () => syncService.Status == SyncStatus.Error
                  && handler.Requests.Count(r => r.Method == HttpMethod.Post) == 3,
            "Initial push did not exhaust its retries.");
        Assert.False(item.HasSynced);

        await syncService.SyncNowAsync();

        Assert.True(item.HasSynced);
        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.Equal(0, syncService.PendingSyncCount);
        Assert.Equal(4, handler.Requests.Count(r => r.Method == HttpMethod.Post));
    }

    [Fact]
    public async Task Mutations_ProduceAllFourChangeEvents_InOrder()
    {
        var handler = CreateWebhookHandler(HttpStatusCode.Accepted);
        var harness = await CreateHarnessAsync(handler);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        await todoService.AddAsync("Task");
        var item = todoService.Items.Single();
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 1);
        Assert.Equal("todo_added", EventTypeOf(handler.Requests.Single(r => r.Method == HttpMethod.Post)));

        await todoService.ToggleAsync(item);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 2);
        Assert.Equal("todo_completed", EventTypeOf(handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(1)));

        await todoService.ToggleAsync(item);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 3);
        Assert.Equal("todo_reopened", EventTypeOf(handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(2)));

        await todoService.UpdateTitleAsync(item, "Renamed");
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 4);
        Assert.Equal("todo_updated", EventTypeOf(handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(3)));

        await todoService.RemoveAsync(item);
        await WaitUntilAsync(() => handler.Requests.Count(r => r.Method == HttpMethod.Post) == 5);

        var deletedRequest = handler.Requests.Where(r => r.Method == HttpMethod.Post).ElementAt(4);
        Assert.Equal("todo_deleted", EventTypeOf(deletedRequest));

        using var doc = JsonDocument.Parse(deletedRequest.Body!);
        var envelope = Assert.Single(doc.RootElement.EnumerateArray());
        var payload = envelope.GetProperty("payload");
        Assert.Equal(item.Id, payload.GetProperty("id").GetGuid());
        Assert.Equal("Renamed", payload.GetProperty("title").GetString());
        Assert.False(payload.GetProperty("is_completed").GetBoolean());
    }

    [Fact]
    public async Task InitializeAsync_PullsAndReplacesWithoutWebhookEcho()
    {
        var local = new TodoItem { Title = "local", HasSynced = true };
        var settings = SyncSettings();
        settings.LastSyncedAt = OlderCreatedAt; // 早于服务器创建时间

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK,
                    "[{\"id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"title\":\"Pulled A\",\"is_completed\":false,\"created_at\":\"2026-08-10T17:00:00+08:00\",\"completed_at\":null}," +
                    "{\"id\":\"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\",\"title\":\"Pulled B\",\"is_completed\":true,\"created_at\":\"2026-08-10T17:05:00+08:00\",\"completed_at\":\"2026-08-10T17:10:00+08:00\"}]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.Equal(2, todoService.Items.Count);
        Assert.Equal("Pulled A", todoService.Items[0].Title);
        Assert.True(todoService.Items.All(x => x.HasSynced));

        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal(ServerCreatedAtNormalized, reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task InitializeAsync_SameCreatedAt_SkipsPullAndKeepsItems()
    {
        var local = new TodoItem { Title = "keep me", HasSynced = true };
        var settings = SyncSettings(); // LastSyncedAt 与服务器 meta created_at 一致

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK, "[{\"Id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"Title\":\"Should not be pulled\"}]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Uri.AbsolutePath.EndsWith("/api/todo"));
        var item = Assert.Single(todoService.Items);
        Assert.Equal("keep me", item.Title);
    }

    [Fact]
    public async Task InitializeAsync_ServerNewerWithLocalPending_OverwritesWithoutPushing()
    {
        var local = new TodoItem { Title = "unsynced", HasSynced = false };
        var settings = SyncSettings();
        settings.LastSyncedAt = OlderCreatedAt; // 早于服务器创建时间

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return new HttpResponseMessage(HttpStatusCode.InternalServerError);
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{LaterCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK,
                    "[{\"id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"title\":\"Pulled C\",\"is_completed\":false,\"created_at\":\"2026-08-10T17:00:00+08:00\",\"completed_at\":null}]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        var item = Assert.Single(todoService.Items);
        Assert.Equal("Pulled C", item.Title);
        Assert.True(todoService.Items.All(x => x.HasSynced));

        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal("2026-08-10T18:00:00.0000000+08:00", reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task InitializeAsync_NullLastSyncedAt_FirstSyncPullsAndOverwrites()
    {
        var local = new TodoItem { Title = "local synced", HasSynced = true };
        var settings = SyncSettings();
        settings.LastSyncedAt = null; // 首次同步：无论本地状态都拉取

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK,
                    "[{\"id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"title\":\"Pulled D\",\"is_completed\":false,\"created_at\":\"2026-08-10T17:00:00+08:00\",\"completed_at\":null}]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        var item = Assert.Single(todoService.Items);
        Assert.Equal("Pulled D", item.Title);
        Assert.True(todoService.Items.All(x => x.HasSynced));

        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal(ServerCreatedAtNormalized, reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task InitializeAsync_ServerOlderThanLastSyncedAt_NoPullPushesPending()
    {
        var local = new TodoItem { Title = "pending", HasSynced = false };
        var settings = SyncSettings();
        settings.LastSyncedAt = LaterCreatedAt; // 晚于服务器创建时间

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK, "[{\"Id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"Title\":\"Should not be pulled\"}]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, settingsRepo, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Uri.AbsolutePath.EndsWith("/api/todo"));
        var item = Assert.Single(todoService.Items);
        Assert.Equal("pending", item.Title);
        Assert.True(item.HasSynced);

        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal(LaterCreatedAt, reloaded.LastSyncedAt);
    }

    [Fact]
    public async Task InitializeAsync_MissingCreatedAt_MetaError()
    {
        var local = new TodoItem { Title = "untouched", HasSynced = true };
        var settings = SyncSettings();

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, "{\"date\":\"2026-08-10\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK, "[]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Error, syncService.Status);
        Assert.Contains("created_at", syncService.LastError);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.DoesNotContain(handler.Requests, r => r.Uri.AbsolutePath.EndsWith("/api/todo"));
        var item = Assert.Single(todoService.Items);
        Assert.Equal("untouched", item.Title);
    }

    [Fact]
    public async Task InitializeAsync_SameTimestamp_WithLocalPending_PushesPending()
    {
        var local = new TodoItem { Title = "pending", HasSynced = false };
        var settings = SyncSettings(); // LastSyncedAt == meta created_at

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK, "[]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, local);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Uri.AbsolutePath.EndsWith("/api/todo"));
        var post = Assert.Single(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.Equal("todo_updated", EventTypeOf(post));
        var item = Assert.Single(todoService.Items);
        Assert.Equal("pending", item.Title);
        Assert.True(item.HasSynced);
    }

    [Fact]
    public async Task InitializeAsync_PushesMultiplePendingItemsInSingleBatch()
    {
        var localA = new TodoItem { Title = "A", HasSynced = false };
        var localB = new TodoItem { Title = "B", HasSynced = false };
        var settings = SyncSettings(); // LastSyncedAt == meta created_at

        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{ServerCreatedAt}\"}}");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler, settings, localA, localB);
        var (todoService, _, syncService, _) = harness;

        await syncService.InitializeAsync();

        Assert.Equal(SyncStatus.Success, syncService.Status);
        var post = Assert.Single(handler.Requests, r => r.Method == HttpMethod.Post);

        using var doc = JsonDocument.Parse(post.Body!);
        var root = doc.RootElement;
        Assert.Equal(JsonValueKind.Array, root.ValueKind);
        Assert.Equal(2, root.GetArrayLength());
        Assert.All(root.EnumerateArray(), e => Assert.Equal("todo_updated", e.GetProperty("event_type").GetString()));
        var ids = root.EnumerateArray()
            .Select(e => e.GetProperty("payload").GetProperty("id").GetGuid())
            .OrderBy(id => id)
            .ToList();
        Assert.Equal(new[] { localA.Id, localB.Id }.OrderBy(id => id).ToList(), ids);
        Assert.All(todoService.Items, item => Assert.True(item.HasSynced));
        Assert.Equal(0, syncService.PendingSyncCount);
    }

    [Fact]
    public async Task SyncNowAsync_ServerUpdatedLater_PullsWithoutPushing()
    {
        var currentMetaCreatedAt = ServerCreatedAt;
        var handler = new FakeHttpMessageHandler(request =>
        {
            if (request.Method == HttpMethod.Post)
                return JsonResponse(HttpStatusCode.Accepted, "{\"status\":\"accepted\"}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo/meta"))
                return JsonResponse(HttpStatusCode.OK, $"{{\"date\":\"2026-08-10\",\"created_at\":\"{currentMetaCreatedAt}\"}}");
            if (request.RequestUri!.AbsolutePath.EndsWith("/api/todo"))
                return JsonResponse(HttpStatusCode.OK,
                    "[{\"id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"title\":\"Pulled E\",\"is_completed\":false,\"created_at\":\"2026-08-10T17:00:00+08:00\",\"completed_at\":null}]");
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        });

        var harness = await CreateHarnessAsync(handler);
        var (todoService, settingsRepo, syncService, _) = harness;

        // 等值：不拉取、不推送
        await syncService.SyncNowAsync();
        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        Assert.DoesNotContain(handler.Requests, r => r.Uri.AbsolutePath.EndsWith("/api/todo"));

        // 服务器更新：拉取覆盖，不推送
        currentMetaCreatedAt = LaterCreatedAt;
        await syncService.SyncNowAsync();
        Assert.Equal(SyncStatus.Success, syncService.Status);
        Assert.DoesNotContain(handler.Requests, r => r.Method == HttpMethod.Post);
        var item = Assert.Single(todoService.Items);
        Assert.Equal("Pulled E", item.Title);
        Assert.True(todoService.Items.All(x => x.HasSynced));

        var reloaded = await settingsRepo.LoadAsync();
        Assert.Equal("2026-08-10T18:00:00.0000000+08:00", reloaded.LastSyncedAt);
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
}

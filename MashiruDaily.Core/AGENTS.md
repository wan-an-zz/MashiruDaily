# AGENTS.md — MashiruDaily.Core（领域层与同步子系统）

> 本目录是纯 .NET 领域层（net10.0），**禁止引用 Avalonia**。命名空间仍是 `MashiruDaily.*`。三端（桌面 / TUI / 移动）共用，改这里影响所有客户端。

## 概览

核心职责三块：Todo 领域模型与存储（`TodoService` + `JsonTodoRepository`）、Hermes 同步子系统（`HermesSyncService` + `HermesWebhookSigner` + `JsonHermesSettingsRepository`）、Todo 页面视图模型（TUI 直接消费）。权威同步契约见 `docs/design/通信协议.md`。

## WHERE TO LOOK

| 目录 | 内容 | 备注 |
|---|---|---|
| `Models/` | `TodoItem`、`HermesSettings` | 数据形状；`HermesSettings.CreateDefault()`（`SyncEnabled=false`） |
| `Abstracts/` | `ITodoService`、`ITodoRepository`、`IHermesSettingsRepository`、`IHermesSyncService` | 接口契约文档里钉了防回环语义，改前先读 |
| `Services/` | 两个 Json 仓库 + TodoService + Hermes 三件套 | 同步子系统的全部核心逻辑 |
| `Converters/` | `LocalDateTimeJsonConverter` | Unspecified 的 DateTime 按本地时间解释 |
| `Logging/` | `LoggingConfigurator` | NLog 纯代码配置，无 nlog.config |
| `ViewModels/` | `ViewModelBase`、`Todo/TodoPageViewModel`+`TodoItemViewModel` | 拆待完成/已完成两集合；TUI 直接消费 |

## 同步子系统（改代码前必读）

- **防回环**：拉取覆盖时 `_suppressChanged = true`；`MarkSyncedAsync` 不触发 `Changed`。破坏任一 → webhook 回声/死循环。
- **事件类型 5 种**：`todo_added`/`todo_updated`/`todo_completed`/`todo_reopened`/`todo_deleted`，payload 一律为完整条目快照（camelCase：`isCompleted`/`createdAt`/`completedAt`）。
- **`HasSynced` 是本地字段，任何事件不得传输**（envelope 只序列化 id/title/isCompleted/createdAt/completedAt）。
- **串行分发**：事件逐个 POST（限流安全），429 退避 2s，`MaxRetryAttempts+1` 次后置 `Error`；队列入队/分发**调用方必须持有 `_gate`**。
- **`ServerBaseUrl` 陷阱**：默认空串，**无**「默认同 `HermesBaseUrl`」回退逻辑；`SyncEnabled` 时 `Validate()` 强制必填 —— 显式填 `http://<主机>:8123`。改拉取逻辑以代码为准，别照抄协议附录默认值。
- **拉取决策**：`GET /api/todo/meta` 比对 `createdAt`，服务器严格更新 → `ReplaceAllAsync` 整表覆盖并持久化 `LastSyncedAt`；否则推送 `HasSynced=false` 条目（`todo_updated` upsert）。
- 签名：`HermesWebhookSigner` HMAC-SHA256 小写 hex，对 `"{timestamp}.{rawBody}"` 原始字节计算；头 `X-Webhook-Timestamp`/`X-Webhook-Signature-V2`/`X-Request-ID`。

## 持久化纪律

- `JsonTodoRepository`/`JsonHermesSettingsRepository`：**原子写**（tmp + move），缺失/损坏按默认值加载，**IO 失败只记日志绝不抛出**。落盘 `%APPDATA%\MashiruDaily\`（`todos.json` 数组 / `settings.json` 对象）。
- `TodoService`：单一数据源，变更抛 `Changed`，单飞冲刷循环落盘**值快照**（`SnapshotItems` 拷贝，防引用漂移）。

## 测试

- `dotnet test MashiruDaily.Tests` 完全离线。同步测试**不 mock `TodoService`**：`CreateHarnessAsync`（临时目录 + 真实 repo/service）+ `FakeHttpMessageHandler` 桩 HTTP + `WaitUntilAsync` 轮询断言。新同步测试沿用该模式。

## ANTI-PATTERNS

- 给 Core 加 Avalonia 依赖（`MashiruDaily.*` UI 类型）— 破坏三端共享边界。
- `_suppressChanged` 用在非拉取路径 / `MarkSyncedAsync` 触发 `Changed` — 死循环。
- 传输 `HasSynced`、用 PascalCase 发 webhook、照抄协议默认 `ServerBaseUrl` — 协议违约或同步恒 Error。
- `catch (Exception ex) { }` 空捕获或 IO 失败向上抛 — 仓库层契约要求「绝不抛出」。

# MashiruDaily.Server 运维手册

> 本文档描述当前代码实际运行的 MashiruDaily.Server：FastAPI 拉取/接收服务器、Hermes 数据工具插件、以及部署装配脚本。

## 1. 架构与数据流

MashiruDaily.Server 是一个轻量 Python 后端，承担三件事：

1. **拉取服务器**：向客户端提供只读 GET 接口，返回 todo 列表、同步元数据和 Agent 消息。
2. **事件接收器**：接收客户端批量推送的待办变更，直接写 `todo.json`。
3. **Hermes 数据工具集**：提供 `todo_*` 与 `speak_to_user` 工具，供 Hermes Agent 每日维护待办数据、给用户留消息。

当前同步数据流：

MashiruDaily 客户端
   │  GET  /api/todo/meta、/api/todo         拉取
   │  GET  /api/messages                     拉取 Agent 消息
   │  POST /api/update                       推送待办变更（批量）
   ▼
FastAPI 服务器（:8123）
   │  直接读写 todo.json / todo-meta.json
   ▼
Hermes Agent（cron 每日运行）
   │  通过 hermes_plugin 的 todo_* 工具维护 todo.json
   │  通过 speak_to_user 写入 messages-to-user.json

MashiruDaily 客户端
   │  POST {HermesBaseUrl}/webhooks/{WebhookRouteName}  推送成功后触发 Agent 反应（后台异步）
   ▼
Hermes Webhook 网关（:8644）

**注意**：数据权威链路仍走 FastAPI `/api/update`。Hermes Webhook 网关（:8644）当前用于在客户端推送成功后触发 Hermes Agent 生成反应消息，客户端再通过 `/api/messages` 拉取该消息。

## 2. 数据文件

默认数据目录（可用 `MASHIRU_DATA_DIR` 覆盖）：

```
$HOME/.mashiru-daily/todos/
├── todo.json                蛇形命名待办数组，服务器侧唯一数据源
├── todo-meta.json           同步元数据：date / created_at / count
└── backups/                 todo_save 覆盖前的备份
```

消息文件位于**数据目录的父目录**（当前代码如此实现）：

```
$HOME/.mashiru-daily/messages-to-user.json
```

内容示例：

```json
{ "text": "今天记得完成数学作业", "time": "2026-08-22T21:00:00+08:00" }
```

## 3. API

### `GET /health`

```json
{ "status": "ok" }
```

### `GET /api/todo/meta`

返回客户端拉取决策用的元数据：

```json
{ "date": "2026-08-22", "created_at": "2026-08-22T08:00:00+08:00", "count": 12 }
```

- `count` 始终是 `todo.json` 的实时条数。
- `todo-meta.json` 缺失时自动创建；结构不合法时返回 `500 {"detail": ...}`。

### `GET /api/todo`

返回蛇形命名待办数组；`todo.json` 缺失时返回 `[]`：

```json
[
  {
    "id": "22222222-2222-2222-2222-222222222222",
    "title": "买菜",
    "is_completed": true,
    "created_at": "2026-08-10T09:00:00+08:00",
    "completed_at": "2026-08-10T11:30:00+08:00"
  }
]
```

### `GET /api/messages`

返回当前 Agent 消息：

```json
{ "exist": true, "text": "今天记得完成数学作业", "time": "2026-08-22T21:00:00+08:00" }
```

- 文件不存在：`200 {"exist": false, "text": "", "time": ""}`
- 文件存在但缺键：`500 {"detail": "messages-to-user.json 文件不合法或已被损坏"}`
- JSON 非法或顶层不是对象：`500 {"detail": "messages-to-user.json 文件不合法或已被损坏"}`

### `POST /api/update`

客户端批量推送待办变更。请求体：

```json
{
  "event_type": "update",
  "events": [
    {
      "event_type": "todo_updated",
      "timestamp": "2026-08-22T21:00:00+08:00",
      "payload": {
        "id": "22222222-2222-2222-2222-222222222222",
        "title": "买菜",
        "is_completed": false,
        "created_at": "2026-08-10T09:00:00+08:00",
        "completed_at": null
      }
    }
  ]
}
```

服务端按 `events[].event_type` 调用 `todo_upsert` / `todo_delete` 直接修改 `todo.json`。

成功响应：

```json
{ "success": true, "error_ids": [], "success_ids": ["22222222-..."] }
```

部分失败（HTTP 500）：

```json
{ "success": false, "error_ids": ["失败 id"], "success_ids": ["成功 id"] }
```

当前 FastAPI 服务端**不校验 HMAC 签名**；客户端仍会发送 `X-Webhook-Timestamp` / `X-Webhook-Signature-V2` / `X-Request-ID` 头，属于保留行为。

## 4. 客户端设置

客户端使用 `RemoteServerSettings`，关键字段如下：

| 字段 | 默认值 | 当前用途 |
|---|---|---|
| `ServerBaseUrl` | 空 | 拉取与推送都走它，如 `http://<主机>:8123` |
| `HermesBaseUrl` | `http://localhost:8644` | Hermes Webhook 基地址：触发 Agent 反应；设置页连接测试也用它 |
| `WebhookRouteName` | `todo-sync` | Hermes Webhook 路由名，用于触发 Agent 反应 |
| `WebhookSecret` | 空 | 用于计算 `/api/update` 与 Hermes Webhook 的 HMAC 签名 |
| `SyncEnabled` | `false` | 同步总开关 |
| `MaxRetryAttempts` | `3` | 推送失败最大重试次数 |
| `TimeoutSeconds` | `10` | HTTP 超时秒数 |
| `LastSyncedAt` | 空 | 上次成功拉取时服务器 `created_at` |

`ServerBaseUrl` 必须显式填写 `http://<主机>:8123`，没有“默认等于 HermesBaseUrl”的回退。

## 5. created_at 语义

- `todo-meta.json` 的 `created_at` 只在 `todo_meta_stamp` 运行时变化。
- 运行时机：`setup_server.py` 首次引导、每日 Hermes cron 任务结束。
- 客户端通过 `/api/update` 推送导致 `todo.json` 修改时，**禁止**更新 `created_at`，否则客户端会把每次推送误判为需要全量拉取。

## 6. Hermes 插件工具

`hermes_plugin/mashiru_daily/tools.py` 提供：

`todo_list` / `todo_get` / `todo_save` / `todo_upsert` / `todo_completed` / `todo_delete` / `todo_meta_get` / `todo_meta_stamp` / `speak_to_user`

- 所有 handler 返回 JSON 字符串，不向上抛异常。
- 数据写入一律原子写（tmp + `os.replace`）。
- `speak_to_user` 写入 `$HOME/.mashiru-daily/messages-to-user.json`，内容为 `{text, time}`。

## 7. 部署脚本

仓库提供以下幂等脚本：

| 脚本 | 作用 |
|---|---|
| `setup_server.py` | 创建 `.venv`、安装依赖、创建数据目录、生成初始 `todo-meta.json` |
| `register_hermes_plugin.py` | 把 `hermes_plugin/mashiru_daily` 链接到 Hermes 并启用 |
| `configure_webhook.py` | 配置 Hermes Webhook 网关的 `todo-sync` 路由（用于触发 Hermes Agent 反应） |
| `configure_cron.py` | 创建每日 Hermes cron 任务，维护 `todo.json` |
| `install_autostart.py` | 注册物理开机自启 |
| `bootstrap.py` | 一键串联以上脚本 |
| `uninstall.py` | 卸载部署足迹 |

推荐一键初始化：

```powershell
python bootstrap.py --secret <密钥>
```

## 8. 测试

离线测试：

```powershell
pytest MashiruDaily.Server/tests -v
```

## 9. 端口

| 端口 | 用途 |
|---|---|
| `8123` | FastAPI 拉取/接收服务器，默认监听 `0.0.0.0` |
| `8644` | Hermes Webhook 网关（触发 Hermes Agent 反应） |

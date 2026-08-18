---
name: webhook-todo-sync
description: Webhook 待办同步：接收 MashiruDaily 客户端的批量 todo_* 事件数组（每个请求最多 15 个事件，类型为 todo_added / todo_updated / todo_completed / todo_reopened / todo_deleted）并根据事件和业务数据修改 todo.json。webhook 路由触发的 agent 处理事件时使用。
---

# Webhook 待办同步（Webhook Todo Sync）

## 何时使用

- 要求同步 todo.json 时，且请求体是一个包含 1 到 15 个 Todo 变更事件的 JSON 数组。

## 定位与分工

**本 Skill 只做每个事件对应的最小修改，绝不使用 todo_save 工具全量覆盖**

## 前置条件

1. **MashiruDaily 插件已安装**：工具集 `mashiru_daily`（含 `todo_upsert` / `todo_completed` / `todo_delete` 等 8 个工具）可用。
2. **todo.json 可写**：插件数据目录（`MASHIRU_DATA_DIR`）权限正常。

## 工作流程

```
Step 1 解析请求体（JSON 数组，最多 15 个事件）
     ↓
Step 2 按顺序逐个事件查映射表
     ↓
Step 3 逐个调用工具修改 todo.json
     ↓
Step 4 校验写入结果
```

### Step 1 解析请求体

- 请求体是一个 **JSON 数组**，每个元素是一个 Todo 变更事件。
- 每个事件对象包含：
  - `event_type`：五种事件类型之一；
  - `timestamp`：事件发生时间（ISO 8601）；
  - `payload`：完整条目快照，包含 `id` / `title` / `is_completed` / `created_at` / `completed_at`。
- **必须遍历处理数组中的全部事件**，不能只处理第一个或最后一个。
- 如果某个事件的 `event_type` 不在五种事件类型内：**跳过该事件，不要动 todo.json**，继续处理后续事件，最后如实报告跳过了哪些事件。

### Step 2 事件类型 → 工具映射表

| 事件类型             | 调用工具                                 | 参数                                           | 动作                        |
| ---------------- | ------------------------------------ | -------------------------------------------- | ------------------------- |
| `todo_added`     | **TODO_UPSERT**（`todo_upsert`）       | `id` + `title` + `is_completed` + `completed_at`（均必填） | 若 id 不存在则新建该 id 的待办；已存在则更新标题/完成状态/完成时间（幂等） |
| `todo_updated`   | **TODO_UPSERT**（`todo_upsert`）       | `id` + `title` + `is_completed` + `completed_at`（均必填） | 按 id 更新标题/完成状态/完成时间；id 不存在则新建该 id 的待办 |
| `todo_completed` | **TODO_COMPLETED**（`todo_completed`） | `id` + `completed: true` + `completed_at`（均必填） | 将指定项标记为完成，completed_at 与客户端同步 |
| `todo_reopened`  | **TODO_COMPLETED**（`todo_completed`） | `id` + `completed: false` + `completed_at`（均必填） | 将指定项重开为未完成，completed_at 与客户端同步 |
| `todo_deleted`   | **TODO_DELETED**（`todo_delete`）      | `id`                                         | 删除 todo.json 中的指定项        |

### Step 3 调用工具

按 Step 2 映射表，对数组中的**每一个事件**逐个调用工具，参数示例：

- 新增/更新：`todo_upsert({"id": "30c27205-…", "title": "数学｜模块6·类型2 抽象函数 必刷一百讲", "is_completed": false, "completed_at": null})`
- 完成：`todo_completed({"id": "30c27205-…", "completed": true, "completed_at": "2026-08-17T18:00:00+08:00"})`
- 重开：`todo_completed({"id": "30c27205-…", "completed": false, "completed_at": null})`
- 删除：`todo_delete({"id": "30c27205-…"})`

注意：

- `todo_upsert` 的 `is_completed` / `completed_at` 直接取自客户端 payload，必须原样透传，不要自行生成或清空。
- `todo_completed` 的 `completed_at` 也直接透传客户端值；是否完成以 `event_type` 和 `completed` 为准。
- 多个事件可能操作同一个 `id`，必须按数组顺序依次处理，后一个事件基于前一个事件的结果继续。

### Step 4 校验

- 全部事件处理完后，用 **TODO_GET**（`todo_get`，按 id 查单条）或 **TODO_LIST**（`todo_list`，查全量）复查，确认变更生效、字段语义正确。
- 工具返回 `{"success": false, ...}`（如缺少参数，或 completed/delete 遇到未知 id）时：**如实报告**，不要编造成功结果。

## 完整示例（虚构批量事件走一遍）

**场景**：你收到了这样一条 prompt：

```
sync these todo changes to todo.json:
[{"event_type":"todo_added","timestamp":"2026-08-17T17:00:00+08:00","payload":{"id":"30c27205-aaaa-4a80-b0cf-0f47645af157","title":"数学｜模块6·类型2 抽象函数 必刷一百讲","is_completed":false,"created_at":"2026-08-17T17:00:00+08:00","completed_at":null}},{"event_type":"todo_completed","timestamp":"2026-08-17T17:01:00+08:00","payload":{"id":"40c27205-bbbb-4a80-b0cf-0f47645af158","title":"英语单词","is_completed":true,"created_at":"2026-08-17T16:00:00+08:00","completed_at":"2026-08-17T17:01:00+08:00"}}]
```

1. **解析**：请求体是数组，包含两个事件：
   - 第一个是 `todo_added`，`id` 为 `30c27205-…`，`title` 为 `数学｜模块6·类型2 抽象函数 必刷一百讲`，`is_completed` 为 `false`，`completed_at` 为 `null`；
   - 第二个是 `todo_completed`，`id` 为 `40c27205-…`，`completed_at` 为 `2026-08-17T17:01:00+08:00`。
2. **处理第一个事件**：查映射表，`todo_added` 使用 TODO_UPSERT，参数 `id` + `title` + `is_completed` + `completed_at`。
3. **调用**：`todo_upsert({"id": "30c27205-aaaa-4a80-b0cf-0f47645af157", "title": "数学｜模块6·类型2 抽象函数 必刷一百讲", "is_completed": false, "completed_at": null})`。
4. **处理第二个事件**：查映射表，`todo_completed` 使用 TODO_COMPLETED，参数 `id` + `completed: true` + `completed_at`。
5. **调用**：`todo_completed({"id": "40c27205-bbbb-4a80-b0cf-0f47645af158", "completed": true, "completed_at": "2026-08-17T17:01:00+08:00"})`。
6. **校验**：`todo_list` 复查，确认两条变更都生效。完成。✅

## 陷阱与注意事项

1. **只做最小修改，禁止 todo_save 全量覆盖**：全量重建会丢掉并发写入的其他数据。
2. **请求体是数组，必须处理全部事件**：每个请求最多 15 个事件，遗漏任何一个都会造成客户端与服务端数据不一致。
3. **`completed` 必须是布尔**：TODO_COMPLETED 对非布尔（如字符串 `"true"`）直接拒绝。
4. **todo_upsert 必须传 id、title、is_completed、completed_at**：id 已存在则更新标题/完成状态/完成时间，id 不存在则新建该 id 的待办；completed_at 与客户端同步，不要自行生成或清空。
5. **todo_completed 必须传 id、completed、completed_at**：completed_at 与客户端同步，不要自行生成或清空。
6. **无法识别的事件不动作**：event_type 不在五种之内时，不写入、不脑补，跳过并继续处理其他事件。
7. **写完必校验**：用 todo_get / todo_list 复查，确认条数与字段语义正确再回复完成。

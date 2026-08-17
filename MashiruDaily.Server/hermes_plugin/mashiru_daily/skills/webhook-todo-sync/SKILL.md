---
name: webhook-todo-sync
description: Webhook 待办同步：接收 MashiruDaily 客户端的 todo_* 事件（todo_added / todo_updated / todo_completed / todo_reopened / todo_deleted）并根据事件和业务数据修改 todo.json。webhook 路由触发的 agent 处理事件时使用。
---

# Webhook 待办同步（Webhook Todo Sync）

## 何时使用

- 要求同步todo.json时

## 定位与分工

**本 Skill 只做事件对应的最小修改，绝不 使用 todo_save 工具全量覆盖**

## 前置条件

1. **MashiruDaily 插件已安装**：工具集 `mashiru_daily`（含 `todo_upsert` / `todo_completed` / `todo_delete` 等 8 个工具）可用。
2. **todo.json 可写**：插件数据目录（`MASHIRU_DATA_DIR`）权限正常。

## 工作流程

```
Step 1 明确event_type、title和id
     ↓
Step 2 按 event_type 查映射表，确定要调用的工具与参数
     ↓
Step 3 调用工具修改 todo.json
     ↓
Step 4 校验写入结果
```

### Step 1 解析事件体

- 读 `event_type`, `title`, `id`，明确事件类型、todo的标题和todo的id。
- ⚠️ 若`event_type` 不在五种事件类型内：**不要动 todo.json**，如实报告「无法识别的事件」，不做任何写入。

### Step 2 事件类型 → 工具映射表

| 事件类型             | 调用工具                                 | 参数                                           | 动作                        |
| ---------------- | ------------------------------------ | -------------------------------------------- | ------------------------- |
| `todo_added`     | **TODO_UPSERT**（`todo_upsert`）       | `title`（必填，= todo的标题）                        | 向 todo.json 写入一条新的 todo 项 |
| `todo_updated`   | **TODO_UPSERT**（`todo_upsert`）       | `id` + `title`（`id`＝todo的id；`title`＝todo的标题） | 修改 todo.json 中指定项的标题      |
| `todo_completed` | **TODO_COMPLETED**（`todo_completed`） | `id` + `completed: true`                     | 将指定项标记为完成                 |
| `todo_reopened`  | **TODO_COMPLETED**（`todo_completed`） | `id` + `completed: false`                    | 将指定项重开为未完成                |
| `todo_deleted`   | **TODO_DELETED**（`todo_delete`）      | `id`                                         | 删除 todo.json 中的指定项        |

### Step 3 调用工具

按 Step 2 映射表调用，参数示例：

- 新增：`todo_upsert({"title": "数学｜模块6·类型2 抽象函数 必刷一百讲"})`
- 更新：`todo_upsert({"id": "30c27205-…", "title": "数学｜模块6·类型2 抽象函数（改）"})`
- 完成：`todo_completed({"id": "30c27205-…", "completed": true})`
- 重开：`todo_completed({"id": "30c27205-…", "completed": false})`
- 删除：`todo_delete({"id": "30c27205-…"})`
- 
### Step 4 校验

- 调用完成后，用 **TODO_GET**（`todo_get`，按 id 查单条）或 **TODO_LIST**（`todo_list`，查全量）复查，确认变更生效、字段语义正确。
- 工具返回 `{"success": false, "found": false, …}`（未知 id）时：**如实报告未找到**，不要编造成功结果。

## 完整示例（虚构事件走一遍）

**场景**：你收到了这样一条prompt：

```
sync this todo change to todo.json:
event_type: todo_completed
title: 数学｜模块6·类型2 抽象函数 必刷一百讲
id: 30c27205-…
```



1. **解析**：`event_type `为 `todo_completed`，`id`为 `30c27205-…`, `title` 为 `数学｜模块6·类型2 抽象函数 必刷一百讲`。
2. **查映射表**：`todo_completed` 使用 TODO_COMPLETED工具，参数 `id` + `completed: true`。
3. **调用**：`todo_completed({"id": "30c27205-ff93-4a80-b0cf-0f47645af157", "completed": true})`。
4. **校验**：`todo_get({"id": "30c27205-…"})` 复查 → `IsCompleted: true`，`CompletedAt` 已由程序生成（UTC，Z 结尾）。完成。✅

## 陷阱与注意事项

1. **只做最小修改，禁止 todo_save 全量覆盖**：全量重建会丢掉并发写入的其他数据。
2. **`completed` 必须是布尔**：TODO_COMPLETED 对非布尔（如字符串 `"true"`）直接拒绝。
3. **未知 id 如实报告**：completed/delete 遇到不存在的 id 返回 `success=false, found=false`，此时数据没被改，如实告知用户/记录，不要伪造成功。
4. **无法识别的事件不动作**：event_type 不在五种之内时，不写入、不脑补，只报告。
5. **写完必校验**：用 todo_get / todo_list 复查，确认条数与字段语义正确再回复完成。

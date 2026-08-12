---
name: mashiru-todo
description: "维护 MashiruDaily 服务器端的 todo.json 与 plan.md（每日更新与 Webhook 事件处理）"
version: 1.0.0
author: MashiruDaily
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [todo, planning, daily]
    category: productivity
---

# mashiru-todo — 服务器端待办维护

本技能指导 Hermes Agent 维护 MashiruDaily 服务器端的待办数据：`data/todo.json`（数据源）与 `data/plan.md`（当日规划）。客户端（Avalonia 桌面 / Android / TUI）通过 `GET /api/todo` 拉取这份数据，因此**一切修改必须严格遵守本文件规定的 schema 与纪律**。

## When to Use (何时使用)

在以下场景激活本技能：

- **每日 cron 提醒**：每日定时任务通过 `--skill mashiru-todo` 调用，用于刷新当日规划并更新 `todo.json` 的时间戳。
- **Webhook 事件**：服务器收到 `todo_*` 事件（`todo_updated` / `todo_deleted`）时，按事件类型对 `data/todo.json` 执行对应变更。
- **用户直接请求**：用户要求增删改待办、查看计划或整理当天安排。

如果当前没有任何可做的变更（例如事件与现有数据一致、或今日规划已是最新），直接回复 `[SILENT]`，不要产生无意义的写入。

## Data Files (数据文件)

本技能只读写两个文件，均相对于 **MashiruDaily.Server** 根目录：

### data/todo.json

PascalCase JSON 数组，元素字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `Id` | string | GUID 字符串，客户端主键，全局唯一 |
| `Title` | string | 待办标题 |
| `IsCompleted` | bool | 是否已完成 |
| `CreatedAt` | string | ISO 8601 时间戳（带时区偏移） |
| `CompletedAt` | string \| null | 完成时间，未完成时为 `null` |

完整示例：

```json
{
  "Id": "22222222-2222-2222-2222-222222222222",
  "Title": "买菜",
  "IsCompleted": false,
  "CreatedAt": "2026-08-10T09:00:00+08:00",
  "CompletedAt": null
}
```

**绝不添加 `HasSynced` 字段**，它是客户端本地字段，任何事件都不得传输，协议强制禁止。

### data/plan.md

当日规划，Markdown 格式。内容按天组织，维护今日日期与任务清单。

## Procedure (工作流程)

按以下步骤执行，任何一步都不许跳过：

1. **读取** `data/todo.json` 与 `data/plan.md`，掌握当前数据状态。
2. **按事件或日期更新**：
   - `todo_updated`：**upsert**。按 `Id` 查找，存在则更新该条目（`Title` / `IsCompleted` / `CompletedAt`），不存在则用 payload 创建新条目。
   - `todo_deleted`：按 `Id` 删除对应条目。
   - 每日更新：为今日新增/调整待办，刷新 `plan.md` 的当日小节。
3. **维护今日日期字段**：确保 `CreatedAt` / `CompletedAt` 使用 ISO 8601 且带时区，日期与今日一致。
4. **处理完毕后运行 `python tools/stamp_todo_meta.py`**（工作目录必须为 MashiruDaily.Server），刷新 `data/todo-meta.json` 的 `createdAt` 与 `count`。此脚本是**唯一**允许写入 `todo-meta.json` 的入口。
5. **无事可做时**回复 `[SILENT]`。

## Pitfalls (陷阱)

- **绝不修改 `data/todo-meta.json`**：它只能由 `tools/stamp_todo_meta.py` 生成。手工改动会破坏协议：客户端比较 `createdAt` 与本地 `LastSyncedAt`，元数据变了客户端就会在每次 webhook 同步后重复整表拉取，造成回声与死循环。
- **绝不传输 `HasSynced`**：该字段是客户端本地标记，出现在任何事件 payload 中都会导致协议违规。
- **保持 PascalCase 字段名精确**：客户端用 System.Text.Json 反序列化，**大小写敏感**，`Id` 写成 `id`、`CreatedAt` 写成 `createdAt` 都会导致字段丢失。
- **保持 JSON 合法**：写完必须校验，运行 `python -m json.tool data/todo.json` 确认无语法错误。非法 JSON 会让整个 `GET /api/todo` 接口 500，影响所有客户端。
- **webhook 驱动的小改动不要碰 `createdAt` 语义**：`createdAt` 只在每日 cron 重新生成 `todo.json` 时自然变化，webhook 编辑应保持原条目的 `CreatedAt` 不变。

## Verification (验证)

每次修改完成后，必须验证：

1. **JSON 可解析**：

   ```
   python -c "import json;print(len(json.load(open('data/todo.json'))))"
   ```

   应打印条目数量（≥0），无异常输出。

2. **Meta 正确**：

   ```
   curl http://localhost:8123/api/todo/meta
   ```

   确认返回的 `count` 与 `todo.json` 条目数一致，`createdAt` 为最近一次 `stamp_todo_meta.py` 刷新后的时间。

3. **数据一致性**：抽查新增/修改的条目，`Id` 为合法 GUID，`Title` 非空，`IsCompleted` 与 `CompletedAt` 语义一致（完成则 `CompletedAt` 非空，反之 `null`）。

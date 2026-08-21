---
name: todo-updating-and-observation
description: 需要对todo.json做出任意更改或查看todo.json时使用
---

## Todo更新与查看（todo-updating-and-observation）

## 何时使用

- 要求修改或更新`todo.json`时
- 要求修改任意Todo项时
- 要求查看`todo.json`时

## 前置条件

1. **MashiruDaily 插件已安装**：工具集 `mashiru_daily`（含 `todo_upsert` / `todo_completed` / `todo_delete` 等 8 个工具）可用。
2. **todo.json 可写**：插件数据目录（`MASHIRU_DATA_DIR`）权限正常。

## 工作流程

```
Step 1 明确需要进行的修改
     ↓
Step 2 根据修改内容选择合适的工具
     ↓
Step 3 调用工具修改 todo.json
     ↓
Step 4 刷新 `todo.json` 元数据（重要）
```

### Step 1 明确修改内容

针对Todo总共有这几种修改：

- 增加todo
- 删除todo
- 完成todo
- 重新打开todo
- 修改todo
- 覆写todo.json （危险）
- 查看todo.json
- 查看指定todo
- 读取todo.json元数据
- 刷新todo.json元数据

### Step 2 工具选择

| 任务类型           | 调用工具                               | 参数                                 | 备注                        |
| -------------- | ---------------------------------- | ---------------------------------- | ------------------------- |
| 增加todo         | TODO_UPSERT（`todo_upsert`）         | `title`, `is_completed`            | 向 todo.json 写入一条新的 todo 项 |
| 修改todo         | TODO_UPSERT（`todo_upsert`）         | `title`(修改后), `is_completed`, `id` | 修改 todo.json 中指定项的标题      |
| 完成todo         | TODO_COMPLETED（`todo_completed`）   | `id` + `is_completed: true`        | 将指定项标记为完成                 |
| 重新打开todo       | TODO_COMPLETED（`todo_completed`）   | `id` + `is_completed: false`       | 将指定项重开为未完成                |
| 删除todo         | TODO_DELETED（`todo_delete`）        | `id`                               | 删除 todo.json 中的指定项        |
| 查看指定todo       | TODO_GET（`todo_get`）               | `id`                               | 读取指定的一条todo               |
| 查看todo.json    | TODO_LIST(`todo_list`)             | 无                                  | 读取整个todo.json             |
| 覆写todo.json    | TODO_SAVE(`todo_save`)             | `title`数组                          | 该工具十分危险，将会直接覆盖整个todo.json |
| 读取todo.json元数据 | TODO_META_GET(`todo_meta_get`)     | 无                                  | 读取todo-meta.json          |
| 刷新todo.json元数据 | TODO_META_STAMP(`todo_meta-stamp`) | 无                                  | 当修改todo.json后必须使用         |

### Step 3 调用工具

根据用户的实际需求，自由组合需要调用的工具。

- 新增：`todo_upsert({"title": "数学｜模块6·类型2 抽象函数 必刷一百讲", "is_completed": "false"})`
- 更新：`todo_upsert({"id": "30c27205-…", "title": "数学｜模块6·类型2 抽象函数（改）", "is_completed": "false"})`
- 完成：`todo_completed({"id": "30c27205-…", "is_completed": true})`
- 重开：`todo_completed({"id": "30c27205-…", "is_completed": false})`
- 删除：`todo_delete({"id": "30c27205-…"})`

### Step 4 校验修改结果

- 调用完成后，用 **TODO_GET**（`todo_get`，按 id 查单条）或 **TODO_LIST**（`todo_list`，查全量）复查，确认变更生效、字段语义正确。
- 工具返回 `{"success": false, "found": false, …}`（未知 id）时：**如实报告未找到**，不要编造成功结果。

### Step 5 刷新 `todo.json` 元数据

> [!IMPORTANT]
> 完成操作后，必须刷新 `todo.json` 元数据，即调用一次 `todo-meta-stamp`工具，否则用户将无法接收到你的修改。若Step 4校验失败，则不进行这一步

## 完整示例（虚构事件走一遍）

**场景**：你收到了这样一条prompt：

```
增加一个数学模块6 类型2 抽象函数的任务
```

1. **解析**：任务类型为 `增加todo`，可以调用 `todo_upsert`工具
2. **调用**：`todo_upsert({"title": "数学| 模块6·类型2·抽象函数 必刷100讲", "is_completed": false})`。
3. **校验**：`todo_list()` 找到对应 `title` → todo正确，完成。✅
4. **盖章**：调用 `todo-meta-stamp`盖章

## 陷阱与注意事项

1. **`is_completed` 必须是布尔**：TODO_COMPLETED 对非布尔（如字符串 `"true"`）直接拒绝。
2. **未知 id 如实报告**：completed/delete 遇到不存在的 id 返回 `success=false, found=false`，此时数据没被改，如实告知用户/记录，不要伪造成功。
3. **写完必校验**：用 todo_get / todo_list 复查，确认条数与字段语义正确再回复完成。
4. **校验失败不盖章**：如果Step 4校验失败了，一定不能进行Step 5，而是如实报告用户。

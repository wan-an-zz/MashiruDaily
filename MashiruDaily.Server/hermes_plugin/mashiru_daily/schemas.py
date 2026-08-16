"""Hermes 插件工具 Schema：这些描述是 LLM 判断何时调用工具的依据。

所有工具都围绕 MashiruDaily.Server 的 data/todo.json 与 data/todo-meta.json：
- todo.json：PascalCase 待办数组，是服务器侧唯一数据源；
- todo-meta.json：侧车文件，createdAt 只能由 todo_meta_stamp 工具（或等价脚本）
  刷新，webhook 驱动的修改不得触碰。
"""

# 单条待办的 JSON Schema 描述（与 C# 端字段大小写严格一致）
_TODO_ITEM_SCHEMA = {
    "type": "object",
    "description": "一条 PascalCase 待办记录：Id/Title/IsCompleted/CreatedAt/CompletedAt，禁止出现 HasSynced",
    "properties": {
        "Id": {"type": "string", "description": "GUID 字符串，客户端主键"},
        "Title": {"type": "string", "description": "待办标题"},
        "IsCompleted": {"type": "boolean", "description": "是否已完成"},
        "CreatedAt": {"type": "string", "description": "ISO 8601 创建时间（带时区）"},
        "CompletedAt": {"type": ["string", "null"], "description": "ISO 8601 完成时间，未完成时为 null"},
    },
    "required": ["Id", "Title", "IsCompleted", "CreatedAt", "CompletedAt"],
    "additionalProperties": False,
}

TODO_LIST = {
    "name": "todo_list",
    "description": "读取 MashiruDaily 服务器端的 data/todo.json，返回全部待办列表。文件缺失时返回空列表。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TODO_GET = {
    "name": "todo_get",
    "description": "按 Id 从 data/todo.json 中读取一条待办；不存在时返回 success=false。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "待办 Id（GUID 字符串）"},
        },
        "required": ["id"],
    },
}

TODO_SAVE = {
    "name": "todo_save",
    "description": "整体覆盖写入 data/todo.json。传入完整待办数组；用于全量替换，日常增删改用 todo_upsert / todo_delete。",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "完整的 PascalCase 待办数组，不得包含 HasSynced",
                "items": _TODO_ITEM_SCHEMA,
            },
        },
        "required": ["items"],
    },
}

TODO_UPSERT = {
    "name": "todo_upsert",
    "description": "按 Id 对 data/todo.json 做 upsert：Id 已存在则更新该条，不存在则新增。payload 必须为完整条目快照。",
    "parameters": {
        "type": "object",
        "properties": {
            "item": _TODO_ITEM_SCHEMA,
        },
        "required": ["item"],
    },
}

TODO_DELETE = {
    "name": "todo_delete",
    "description": "按 Id 从 data/todo.json 中删除一条待办；不存在时返回 success=false。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "待办 Id（GUID 字符串）"},
        },
        "required": ["id"],
    },
}

TODO_META_GET = {
    "name": "todo_meta_get",
    "description": "读取 data/todo-meta.json 元数据（date/createdAt/count）。侧车缺失时按当前数据初始化并返回；count 始终取 todo.json 实时条数。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TODO_META_STAMP = {
    "name": "todo_meta_stamp",
    "description": "刷新 data/todo-meta.json：更新 date 为今日、createdAt 为当前 UTC、count 为实时条数。仅在每日例行维护结束时调用；webhook 驱动的小改动禁止调用本工具。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

# 统一注册表：name -> schema
TOOLS = {
    TODO_LIST["name"]: TODO_LIST,
    TODO_GET["name"]: TODO_GET,
    TODO_SAVE["name"]: TODO_SAVE,
    TODO_UPSERT["name"]: TODO_UPSERT,
    TODO_DELETE["name"]: TODO_DELETE,
    TODO_META_GET["name"]: TODO_META_GET,
    TODO_META_STAMP["name"]: TODO_META_STAMP,
}

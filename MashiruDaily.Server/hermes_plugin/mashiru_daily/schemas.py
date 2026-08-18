"""Hermes 插件工具 Schema
"""

TODO_LIST = {
    "name": "todo_list",
    "description": "读取 MashiruDaily 服务器端的 data/todo.json，返回全部待办列表。文件缺失或todo.json为空时返回空列表。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TODO_GET = {
    "name": "todo_get",
    "description": "按 id 从 data/todo.json 中读取一条待办；不存在时返回 success=false。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "待办 id（GUID 字符串）"},
        },
        "required": ["id"],
    },
}

TODO_SAVE = {
    "name": "todo_save",
    "description": "整体覆盖写入 data/todo.json。",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "待办标题数组，仅传标题",
                "items": {"type": "string"},
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}

TODO_UPSERT = {
    "name": "todo_upsert",
    "description": "同步客户端完整待办或新增待办，completed_at与created_at **不建议** 填写",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "待办标题"},
            "is_completed": {"type": "boolean", "description": "是否已完成"},
            "id": {
                "type": "string",
                "description": "待办 id（GUID），已存在则更新，不存在则新建该 id 的待办，为空则自动生成id",
            },
            "completed_at": {
                "type": ["string", "null"],
                "description": "完成时间（ISO 8601，与客户端同步；未完成时为 null）",
            },
            "created_at": {
                "type": ["string", "null"],
                "description": "创建的时间, 为空则继承原本的创建时间"
            }
        },
        "required": ["title", "is_completed"],
        "additionalProperties": False,
    },
}

TODO_COMPLETED = {
    "name": "todo_completed",
    "description": "修改已有待办的完成状态。接收 id、completed 和 completed_at；completed_at 与客户端同步。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "已存在待办的 id（GUID）"},
            "completed": {"type": "boolean", "description": "是否已完成"},
            "completed_at": {
                "type": ["string", "null"],
                "description": "完成时间（ISO 8601，与客户端同步；重开时为 null）",
            },
        },
        "required": ["id", "completed", "completed_at"],
        "additionalProperties": False,
    },
}

TODO_DELETE = {
    "name": "todo_delete",
    "description": "按 id 从 data/todo.json 中删除一条待办；不存在时返回 success=false。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "待办 id（GUID 字符串）"},
        },
        "required": ["id"],
    },
}

TODO_META_GET = {
    "name": "todo_meta_get",
    "description": "读取 data/todo-meta.json 元数据（date/created_at/count）。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TODO_META_STAMP = {
    "name": "todo_meta_stamp",
    "description": "刷新 data/todo-meta.json：更新 date 为今日、created_at 为当前 UTC+8、count 为实时条数。仅在每日例行维护结束时调用。",
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
    TODO_COMPLETED["name"]: TODO_COMPLETED,
    TODO_DELETE["name"]: TODO_DELETE,
    TODO_META_GET["name"]: TODO_META_GET,
    TODO_META_STAMP["name"]: TODO_META_STAMP,
}

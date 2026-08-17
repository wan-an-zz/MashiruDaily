"""Hermes 插件工具 Schema
"""

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
    "description": "按 id 更新已有待办的标题；未传 id 或 id 为空时新增一条待办。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "待办标题"},
            "id": {
                "type": "string",
                "description": "已存在待办的 id（GUID）；省略或为空时表示新增",
            },
        },
        "required": ["title"],
        "additionalProperties": False,
    },
}

TODO_COMPLETED = {
    "name": "todo_completed",
    "description": "修改已有待办的完成状态。接收已存在的 id（GUID）和 completed 布尔值。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "已存在待办的 id（GUID）"},
            "completed": {"type": "boolean", "description": "是否已完成"},
        },
        "required": ["id", "completed"],
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
    "description": "刷新 data/todo-meta.json：更新 date 为今日、created_at 为当前 UTC、count 为实时条数。仅在每日例行维护结束时调用。",
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

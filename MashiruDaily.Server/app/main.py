"""MashiruDaily FastAPI 服务器：提供拉取、消息读取与待办事件接收接口。

契约见 docs/design/通信协议.md。网络 JSON 字段统一使用 snake_case，
不传输客户端本地字段 has_synced。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from json import loads

from app.config import get_settings
from app.funcs import current_meta, load_todo_list, current_messages
from hermes_plugin.mashiru_daily.tools import todo_upsert, todo_delete

app = FastAPI()

class todo_item(BaseModel):
    '''单条todo'''
    id: str
    title: str
    is_completed: bool
    created_at: str
    completed_at: str | None

class Item(BaseModel):
    event_type: str
    timestamp: str
    payload: todo_item

class Items(BaseModel):
    '''update_todo_items接受的请求'''
    event_type: str
    events: list[Item]

class update_todo_msg(BaseModel):
    '''update_todo_items的Response。若存在一条todo推送出现错误，success为False。success = True时，error_ids成员数为0'''
    success: bool
    error_ids: list[str] = []
    success_ids: list[str] = []


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """数据文件非法时统一返回 HTTP 500 JSON，错误详情放在 detail。"""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/todo/meta")
def get_meta() -> dict:
    """返回元数据：date / created_at 透传侧车，count 取 todo.json 实时长度。"""
    return current_meta()


@app.get("/api/todo")
def get_todo_list() -> list:
    """返回 todo.json 全量列表，snake_case 逐字透传（不含 has_synced）；缺失时返回空数组。"""
    return load_todo_list()

@app.get("/api/messages")
def get_messages() -> dict:
    """返回当前 Agent 消息。"""
    return current_messages()


@app.get("/health")
def health() -> dict:
    """健康检查（拉取服务器自身；Hermes Webhook 网关另有 8644 端口上的 /health）。"""
    return {"status": "ok"}

@app.post("/api/update")
async def update_todo_items(items: Items):
    err_item_ids = []
    success_item_ids = []
    for item in items.events:
        if item.event_type != "todo_deleted":
            status = loads(todo_upsert({
                "title": item.payload.title,
                "id": item.payload.id,
                "is_completed": item.payload.is_completed,
                "completed_at": item.payload.completed_at,
                "created_at": item.payload.created_at
            }))

        else:
            status = loads(todo_delete({"id": item.payload.id}))

        if isinstance(status, dict):
            ok = status.get("success")
            if isinstance(ok, bool) and ok == True:
                success_item_ids.append(item.payload.id)
                continue
            elif isinstance(ok, bool) and ok == False:
                err_item_ids.append(item.payload.id)
                continue
            else:
                return JSONResponse(status_code=500, content=update_todo_msg(success=False).model_dump())
        else:
            return JSONResponse(status_code=500, content=update_todo_msg(success=False).model_dump())


    if len(err_item_ids) == 0:
        return update_todo_msg(success=True, success_ids=success_item_ids).model_dump()
    else:
        return JSONResponse(status_code=500, content=
            update_todo_msg(success=False, error_ids=err_item_ids, success_ids=success_item_ids).model_dump())





if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=get_settings().host, port=get_settings().port)

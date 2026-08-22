#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对本地 Hermes Webhook 网关（旧路径）的冒烟测试脚本（仅标准库）。

当前客户端同步已改为 POST {ServerBaseUrl}/api/update，本脚本仅用于验证
仍保留的 Hermes Webhook 网关（:8644）路由是否可用，不属于当前同步链路。
- 向 POST {HermesBaseUrl}/webhooks/todo-sync 发送一个包含多个 todo 事件的 JSON 数组；
- 请求头携带 X-Webhook-Timestamp（Unix 秒）、X-Webhook-Signature-V2
  （对 "{timestamp}.{rawBody}" 的 UTF-8 字节计算小写十六进制 HMAC-SHA256，
  与 C# 客户端 HermesWebhookSigner 完全一致）、X-Request-ID（批量请求 ID）；
- 2xx 视为接受成功，非 2xx 视为失败（退出码 1）；
- --negative 模式下额外用错误密钥发送一次，验证网关返回 401（签名强制校验）。

用法：
    python tools/test_webhook_signed.py --secret <共享密钥>
    MASHIRU_WEBHOOK_SECRET=<共享密钥> python tools/test_webhook_signed.py --url http://<host>:8644/webhooks/todo-sync
    python tools/test_webhook_signed.py --secret <共享密钥> --negative
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# 默认推送端点与两个拉取端点（拉取端点是本项目的 pull server，与本次测试相互独立）
DEFAULT_WEBHOOK_URL = "http://localhost:8644/webhooks/todo-sync"
PULL_META_URL = "http://localhost:8123/api/todo/meta"
PULL_TODO_URL = "http://localhost:8123/api/todo"

# 单次 HTTP 请求超时（与客户端默认 TimeoutSeconds=10 一致）
TIMEOUT_SECONDS = 10


def build_batch() -> tuple[str, bytes]:
    """构造一个包含两个 todo 事件的批量请求体，返回 (batch_id, 原始请求字节)。

    - batch_id 为本次批量请求的 UUID，放入 X-Request-ID；
    - 旧网关使用 JSON 数组事件体，字段为 snake_case；
    - payload 不含 has_synced（客户端本地字段，禁止传输）；
    - 使用紧凑 JSON（separators=(",", ":")），ensure_ascii=False 以保留中文。
    """
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    batch_id = str(uuid.uuid4())
    events = [
        {
            "event_type": "todo_added",
            "timestamp": now,
            "payload": {
                "id": str(uuid.uuid4()),
                "title": f"Webhook 冒烟测试 {now}",
                "is_completed": False,
                "created_at": now,
                "completed_at": None,
            },
        },
        {
            "event_type": "todo_completed",
            "timestamp": now,
            "payload": {
                "id": str(uuid.uuid4()),
                "title": f"Webhook 冒烟测试完成 {now}",
                "is_completed": True,
                "created_at": now,
                "completed_at": now,
            },
        },
    ]
    raw_body = json.dumps(events, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return batch_id, raw_body


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """按协议计算小写十六进制 HMAC-SHA256 签名。

    与 MashiruDaily.Core/Services/HermesWebhookSigner.cs 完全一致：
    对 "{timestamp}.{rawBody}" 的 UTF-8 字节计算，rawBody 即发送的原始字节。
    """
    return hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()


def post_webhook(url: str, secret: str, raw_body: bytes, request_id: str) -> tuple[int | None, str]:
    """发送签名后的 Webhook 请求，返回 (HTTP 状态码, 响应体文本)。

    网络异常时返回 (None, 错误描述)。
    """
    ts = str(int(time.time()))
    signature = compute_signature(secret, ts, raw_body)
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": ts,
        "X-Webhook-Signature-V2": signature,
        "X-Request-ID": request_id,
    }
    print(f"[信息] POST {url}")
    print(f"[信息] X-Webhook-Timestamp   = {ts}")
    print(f"[信息] X-Webhook-Signature-V2 = {signature}")
    print(f"[信息] X-Request-ID          = {request_id}")

    request = Request(url, data=raw_body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, body
    except URLError as error:
        return None, f"网络错误：{error.reason}"


def resolve_secret(args: argparse.Namespace) -> str:
    """从 --secret 参数或 MASHIRU_WEBHOOK_SECRET 环境变量获取密钥；缺失则拒绝退出。"""
    secret = args.secret or os.environ.get("MASHIRU_WEBHOOK_SECRET", "")
    if not secret:
        print("[错误] 缺少 Webhook 密钥：请通过 --secret 参数或环境变量 MASHIRU_WEBHOOK_SECRET 提供（须与 Hermes 路由配置一致）。")
        sys.exit(1)
    return secret


def print_pull_commands() -> None:
    """打印两个拉取端点的 curl 检查命令（仅供参考，不实际请求）。"""
    print("\n[信息] 拉取端点检查命令（pull server 端口 8123，与本测试相互独立）：")
    print(f"  curl {PULL_META_URL}")
    print(f"  curl {PULL_TODO_URL}")


def run_positive_test(url: str, secret: str) -> bool:
    """发送签名正确的批量事件，断言 2xx 接受；返回是否成功。"""
    print("\n===== 正向测试：正确密钥签名 =====")
    request_id, raw_body = build_batch()
    status, body = post_webhook(url, secret, raw_body, request_id)
    if status is None:
        print(f"[失败] 无法连接网关：{body}")
        return False
    if 200 <= status < 300:
        print(f"[成功] 网关接受批量事件：HTTP {status}，响应：{body}")
        return True
    print(f"[失败] 网关拒绝事件：HTTP {status}，响应：{body}")
    return False


def run_negative_test(url: str, secret: str) -> bool:
    """用错误密钥发送批量事件，断言网关返回 401（签名强制校验）；返回是否通过。"""
    print("\n===== 负向测试：错误密钥签名（预期 401）=====")
    request_id, raw_body = build_batch()
    wrong_secret = "wrong-secret-" + secret
    status, body = post_webhook(url, wrong_secret, raw_body, request_id)
    if status is None:
        print(f"[失败] 无法连接网关：{body}")
        return False
    if status == 401:
        print(f"[成功] 网关正确拒绝错误签名：HTTP 401，响应：{body}")
        return True
    print(f"[失败] 期望 401，实际 HTTP {status}，响应：{body}")
    return False


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="向本地 Hermes Webhook 网关发送签名正确的批量 todo 事件并验证接受情况（冒烟测试）。",
    )
    parser.add_argument(
        "--secret",
        help="Webhook 共享密钥（HMAC-SHA256 签名用）；也可用环境变量 MASHIRU_WEBHOOK_SECRET 提供。",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_WEBHOOK_URL,
        help=f"Webhook 推送端点（默认 {DEFAULT_WEBHOOK_URL}）。",
    )
    parser.add_argument(
        "--negative",
        action="store_true",
        help="附加负向测试：用错误密钥发送，断言网关返回 401（签名强制校验）。",
    )
    return parser.parse_args()


def main() -> int:
    """主流程：正向测试 + 可选的负向测试，全部通过返回 0，否则返回 1。"""
    args = parse_args()
    secret = resolve_secret(args)

    ok = run_positive_test(args.url, secret)
    if args.negative:
        ok = run_negative_test(args.url, secret) and ok

    print_pull_commands()

    if ok:
        print("\n[成功] 冒烟测试全部通过。")
        return 0
    print("\n[失败] 冒烟测试未通过。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

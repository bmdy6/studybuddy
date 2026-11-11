"""M3 生产验收：跨天旧会话的「今天」计划草案日期 smoke 验证。

背景：P3 草案日期跨天沿用旧日期（bug B4）修复已部署生产。本脚本在 testreg 的长期主会话里
连续发 3 条不同科目（数学/英语/生物）的草案请求（今天、目标、时长齐全、只给草案、不要创建），
解析 SSE，检查：

- stale_today_labels：草案标题/正文里把旧日期直接称为「今天/今日…（YYYY-MM-DD）」的命中数
- wrong_draft_planned_dates：draft_study_plan 工具结果里 planned_date != 服务端今天 的次数
- formal_plan_count_delta：发请求前后正式计划数差值，必须为 0（不得创建正式计划）
- sse_or_http_errors：SSE error 事件 / HTTP 失败次数

约束：
- 只发草案请求，不确认草案、不创建正式计划、不删除任何数据（可重跑、幂等）
- 密码只从环境变量 SMOKE_PASSWORD 读，不硬编码、不打印
- 退出码 0 = 全部指标通过；非 0 = 有指标未达标或脚本失败

用法（生产）：
    cd studybuddy-backend
    SMOKE_PASSWORD='***' .venv/bin/python scripts/verify_study_plan_date_live.py

可选环境变量：
    STUDYBUDDY_BASE_URL   API 根地址，默认 http://127.0.0.1:8001
    SMOKE_USERNAME        测试账号，默认 testreg
可选参数：
    --attempts N          每个科目各发一条（--attempts 实际只影响轮次上限，默认 3 科目全发）
    --require-old-session 严格校验主会话最后一轮来自前一自然日，不满足直接失败
    --no-confirm          兼容 M3 验收命令写法（脚本始终不确认草案，无需该标志）

注意：nginx 生产只对 /sb 前缀放行 POST（/studybuddy/sb 仅 GET 文档路径），
所以 API 根地址用 http://127.0.0.1:8001。
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

WECHAT_TIMEZONE = "Asia/Shanghai"
DEFAULT_API_BASE = "http://127.0.0.1:8001"

# 3 个科目：今天、目标、时长齐全，只给草案不要创建
SUBJECT_PROMPTS = [
    (
        "数学",
        "今天定一个数学一元二次方程练习计划，做 5 道一元二次方程题，预计 20 分钟，"
        "目标是掌握配方法和公式法解一元二次方程。只先给草案，不要创建。",
    ),
    (
        "英语",
        "今天定一个英语阅读理解练习计划，做 2 篇阅读理解，预计 20 分钟，"
        "目标是提高主旨大意题和细节题的准确率。只先给草案，不要创建。",
    ),
    (
        "生物",
        "今天定一个生物细胞呼吸练习计划，梳理有氧呼吸和无氧呼吸的区别，预计 15 分钟，"
        "目标是掌握呼吸作用的场所、产物和能量释放。只先给草案，不要创建。",
    ),
]

# 旧日期标签检测（与后端 date_guard 的窄范围口径一致）：
# 1) 「今天是 YYYY-MM-DD」
# 2) 同一句/行内「今天/今日 …（YYYY-MM-DD）」
_TODAY_IS_DATE_RE = re.compile(r"今天是\s*(\d{4}-\d{2}-\d{2})")
_TODAY_LABEL_PAREN_RE = re.compile(r"(?:今天|今日)[^。！？!?\n；;]*[（(](\d{4}-\d{2}-\d{2})[）)]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n；;]")


def local_today() -> date:
    """服务端统一日期口径：Asia/Shanghai 的今天。"""
    return datetime.now(ZoneInfo(WECHAT_TIMEZONE)).date()


def find_stale_today_labels(text: str, today: date) -> list[str]:
    """找出把「过去日期」直接称为「今天/今日」的标签命中（原样返回命中片段）。

    只报严格早于今天的日期；今天/未来日期不算 stale。
    """
    if not text:
        return []
    hits: list[str] = []
    for m in _TODAY_IS_DATE_RE.finditer(text):
        try:
            parsed = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if parsed < today:
            hits.append(m.group(0))
    for segment in _SENTENCE_SPLIT_RE.split(text):
        if "今天" not in segment and "今日" not in segment:
            continue
        for m in _TODAY_LABEL_PAREN_RE.finditer(segment):
            try:
                parsed = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if parsed < today:
                hits.append(m.group(0))
    return hits


def parse_sse_events(resp: httpx.Response) -> list[dict]:
    """逐行读取 SSE 流（data: {...}\\n\\n），遇到 done/error 即终止，返回事件列表。"""
    events: list[dict] = []
    for raw_line in resp.iter_lines():
        line = (raw_line or "").strip()
        if not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[len("data: "):])
        except json.JSONDecodeError:
            continue
        events.append(evt)
        if evt.get("type") in ("done", "error"):
            break
    return events


def extract_draft_tool_events(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """从 SSE 事件里抽出 draft_study_plan 的 tool_call(input) 与 tool_result(output)。"""
    calls: list[dict] = []
    results: list[dict] = []
    for evt in events:
        if evt.get("type") == "tool_call" and evt.get("name") == "draft_study_plan":
            calls.append(evt)
        elif evt.get("type") == "tool_result" and evt.get("name") == "draft_study_plan":
            results.append(evt)
    return calls, results


def parse_tool_result_output(output: str) -> dict:
    """tool_result 的 output 是 JSON 字符串，解析失败返回 {}。"""
    if not isinstance(output, str):
        return {}
    try:
        parsed = json.loads(output)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


class Api:
    def __init__(self, base_url: str, token: str):
        self.base = base_url
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = httpx.Client(
            timeout=httpx.Timeout(connect=15, read=300, write=30, pool=15),
            follow_redirects=True,
        )

    def url(self, path: str) -> str:
        return self.base.rstrip("/") + path

    def get_json(self, path: str) -> tuple[int, object]:
        resp = self.client.get(self.url(path), headers=self.headers)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = resp.text[:500]
        return resp.status_code, data

    def post_json(self, path: str, body: dict) -> tuple[int, object]:
        resp = self.client.post(self.url(path), json=body, headers=self.headers)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = resp.text[:500]
        return resp.status_code, data

    def post_sse(self, path: str, body: dict) -> tuple[int, list[dict], str]:
        """POST 并读 SSE 流。返回 (http_status, events, error_text)。"""
        try:
            resp = self.client.post(self.url(path), json=body, headers=self.headers)
        except httpx.HTTPError as exc:
            return 0, [], f"HTTP 请求失败: {exc}"
        if resp.status_code != 200:
            return resp.status_code, [], resp.text[:500]
        try:
            events = parse_sse_events(resp)
        except httpx.HTTPError as exc:
            return 0, [], f"SSE 流读取失败: {exc}"
        return resp.status_code, events, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="M3 生产验收：跨天旧会话「今天」草案日期 smoke")
    parser.add_argument("--attempts", type=int, default=3, help="草案请求数（科目数，默认 3）")
    parser.add_argument("--require-old-session", action="store_true",
                        help="严格校验主会话最后一轮来自前一自然日，否则直接失败")
    parser.add_argument("--no-confirm", action="store_true", help="兼容 M3 命令写法（脚本始终不确认草案）")
    args = parser.parse_args()

    base_url = os.environ.get("STUDYBUDDY_BASE_URL", DEFAULT_API_BASE).strip().rstrip("/") or DEFAULT_API_BASE
    username = os.environ.get("SMOKE_USERNAME", "testreg").strip() or "testreg"
    password = os.environ.get("SMOKE_PASSWORD", "").strip()
    if not password:
        print(json.dumps({"batch": "M3", "status": "fail", "error": "缺少环境变量 SMOKE_PASSWORD"}, ensure_ascii=False))
        return 2

    today = local_today()
    today_str = today.isoformat()
    detail_lines: list[str] = []
    blockers: list[str] = []

    # 1. 登录
    api_token = ""
    try:
        client = httpx.Client(timeout=httpx.Timeout(connect=15, read=30, write=30, pool=15), follow_redirects=True)
        resp = client.post(base_url + "/auth/login", json={"username": username, "password": password})
        login_data = resp.json() if resp.status_code == 200 else {}
        client.close()
    except httpx.HTTPError as exc:
        print(json.dumps({"batch": "M3", "status": "fail", "error": f"登录请求失败: {exc}"}, ensure_ascii=False))
        return 1
    if resp.status_code != 200 or not login_data.get("access_token"):
        blockers.append(f"登录失败 HTTP {resp.status_code}: {str(login_data)[:200]}")
        print(json.dumps({"batch": "M3", "status": "fail", "error": blockers[0]}, ensure_ascii=False))
        return 1
    api_token = login_data["access_token"]
    user_id = login_data.get("user_id")
    api = Api(base_url, api_token)

    # 2. 主会话（长期主会话，跨天旧会话场景）
    st, session = api.get_json("/api/chat/sessions/primary")
    if st != 200 or not isinstance(session, dict) or not session.get("id"):
        blockers.append(f"获取主会话失败 HTTP {st}: {str(session)[:200]}")
        print(json.dumps({"batch": "M3", "status": "fail", "error": blockers[0]}, ensure_ascii=False))
        return 1
    session_id = session["id"]
    detail_lines.append(f"主会话 id={session_id}（session_type={session.get('session_type')}）")

    # 3. 会话最后轮日期（前一自然日 = 跨天场景成立）
    st, messages = api.get_json(f"/api/chat/sessions/{session_id}/messages")
    if st != 200 or not isinstance(messages, list):
        blockers.append(f"读取会话消息失败 HTTP {st}: {str(messages)[:200]}")
        print(json.dumps({"batch": "M3", "status": "fail", "error": blockers[0]}, ensure_ascii=False))
        return 1
    last_msg_date = None
    if messages:
        raw = (messages[-1].get("created_at") or "")[:10]
        try:
            last_msg_date = date.fromisoformat(raw)
        except ValueError:
            last_msg_date = None
    yesterday = today - timedelta(days=1)
    if last_msg_date == yesterday:
        detail_lines.append(f"跨天场景确认：主会话最后一轮来自 {last_msg_date}（前一自然日）")
    else:
        msg = (
            f"主会话最后一轮日期为 {last_msg_date}（今天={today_str}），不是前一自然日；"
            "本次仍按旧会话上下文继续（会话历史含前一日旧日期对话），严格跨天首轮条件未完全满足"
        )
        detail_lines.append(msg)
        if args.require_old_session:
            blockers.append("--require-old-session：主会话最后一轮不在前一自然日")
            print(json.dumps({"batch": "M3", "status": "fail", "error": msg}, ensure_ascii=False))
            return 1

    # 4. 正式计划数 before
    st, plans = api.get_json(f"/api/students/{user_id}/study-plans?status=")
    if st != 200 or not isinstance(plans, list):
        blockers.append(f"统计正式计划失败 HTTP {st}: {str(plans)[:200]}")
        print(json.dumps({"batch": "M3", "status": "fail", "error": blockers[0]}, ensure_ascii=False))
        return 1
    before_count = len(plans)

    # 5. 逐科目发草案请求（SSE）
    stale_today_labels = 0
    wrong_draft_planned_dates = 0
    sse_or_http_errors = 0
    completed = 0
    subject_lines: list[str] = []

    for subject, prompt in SUBJECT_PROMPTS[: args.attempts]:
        st, events, err = api.post_sse(
            f"/api/chat/sessions/{session_id}/messages", {"content": prompt}
        )
        if st != 200 or err:
            sse_or_http_errors += 1
            subject_lines.append(f"{subject}：请求失败 HTTP {st} / {err[:120]}")
            detail_lines.append(f"{subject}：请求失败 HTTP {st} / {err[:120]}")
            continue

        final_text = ""
        text_parts: list[str] = []
        has_error_event = False
        calls, results = extract_draft_tool_events(events)
        for evt in events:
            evt_type = evt.get("type")
            if evt_type == "text":
                text_parts.append(evt.get("content") or "")
            elif evt_type == "done":
                final_text = evt.get("content") or ""
            elif evt_type == "error":
                has_error_event = True
                sse_or_http_errors += 1
        if has_error_event:
            subject_lines.append(f"{subject}：SSE error 事件（本轮未完成）")
            detail_lines.append(f"{subject}：SSE error 事件（本轮未完成）")
            continue

        completed += 1
        final_text = final_text or "".join(text_parts)

        # ① 旧日期标签：最终正文 + 草案工具结果标题
        stale_hits: list[str] = []
        stale_hits += find_stale_today_labels(final_text, today)
        draft_titles: list[str] = []
        for result in results:
            output = parse_tool_result_output(result.get("output") or "")
            title = output.get("title")
            if isinstance(title, str):
                draft_titles.append(title)
                stale_hits += find_stale_today_labels(title, today)
        if stale_hits:
            stale_today_labels += len(stale_hits)

        # ② 草案 planned_date
        draft_dates: list[str] = []
        for result in results:
            output = parse_tool_result_output(result.get("output") or "")
            pd = output.get("planned_date")
            if isinstance(pd, str):
                draft_dates.append(pd)
                if pd != today_str:
                    wrong_draft_planned_dates += 1
        # ③ 校验工具参数里的原始 planned_date（仅记录，供诊断）
        raw_input_dates = [str(c.get("input", {}).get("planned_date")) for c in calls]

        if results:
            title_short = draft_titles[0] if draft_titles else "(无标题)"
            subject_lines.append(
                f"{subject}：调用了 draft_study_plan，草案标题「{title_short}」，"
                f"工具结果 planned_date={draft_dates or '无'}，工具入参 planned_date={raw_input_dates or '无'}"
            )
        else:
            subject_lines.append(f"{subject}：未调用 draft_study_plan（纯文本旁路），正文摘要：{final_text[:100]}")

        # 汇总日志
        log_parts = [
            f"{subject}：completed，final_text 长度 {len(final_text)}，stale 命中 {len(stale_hits)}"
        ]
        if raw_input_dates:
            log_parts.append(f"工具入参 planned_date={raw_input_dates}")
        if draft_dates:
            log_parts.append(f"工具结果 planned_date={draft_dates}")
        if stale_hits:
            log_parts.append(f"stale 片段={stale_hits[:3]}")
        detail_lines.append("；".join(log_parts))

    # 6. 正式计划数 after，delta 必须为 0
    st, plans_after = api.get_json(f"/api/students/{user_id}/study-plans?status=")
    if st != 200 or not isinstance(plans_after, list):
        blockers.append(f"复查正式计划失败 HTTP {st}: {str(plans_after)[:200]}")
        print(json.dumps({"batch": "M3", "status": "fail", "error": blockers[0]}, ensure_ascii=False))
        return 1
    after_count = len(plans_after)
    delta = after_count - before_count
    if delta != 0:
        blockers.append(f"正式计划数变化 before={before_count} after={after_count} delta={delta}（不应创建正式计划）")

    if stale_today_labels != 0:
        blockers.append(f"发现 {stale_today_labels} 处把旧日期称为「今天/今日」的标签")
    if wrong_draft_planned_dates != 0:
        blockers.append(f"发现 {wrong_draft_planned_dates} 处草案 planned_date 不是 {today_str}")
    if sse_or_http_errors != 0:
        blockers.append(f"SSE/HTTP 错误 {sse_or_http_errors} 次")
    if completed != args.attempts:
        blockers.append(f"完成 {completed}/{args.attempts} 次草案请求")

    result = {
        "attempts": args.attempts,
        "completed": completed,
        "stale_today_labels": stale_today_labels,
        "wrong_draft_planned_dates": wrong_draft_planned_dates,
        "formal_plan_count_delta": delta,
        "sse_or_http_errors": sse_or_http_errors,
    }
    status = "pass" if not blockers else "fail"
    detail_lines.append(f"正式计划数 before={before_count} after={after_count} delta={delta}")
    output = {
        "batch": "M3",
        "status": status,
        "today": today_str,
        "script_path": os.path.abspath(__file__),
        "result": result,
        "detail": "；".join(subject_lines),
        "log": "；".join(detail_lines),
        "blockers": blockers,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

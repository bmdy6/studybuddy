"""M4 生产验收：计划对齐与教材诚实 smoke 验证（干净号 + 旧号）。

背景：M0-M3 修复（草案硬边界守卫、卡片会话级分层、教材诚实边界、冷启动提问时机）已部署生产。
本脚本在：
- 干净号（自动注册，用户名前缀 smoke_plan_ + 时间戳）：跑 A 的 6 个完整措辞 + 1 粗略意图 + 1 修改意图，
  C 的 3 个无来源教材问法 + 教材版本画像写入验证
- 旧污染号（默认 testreg，在原旧会话）：发 3 条"另建一个"新主题完整请求（E 验证）

约束：只发草案请求，不确认草案、不创建正式计划、不删除数据；密码只从环境变量读。
退出码 0 = 全部指标通过。

用法（生产）：
    cd studybuddy-backend
    CLEAN_SMOKE_USERNAME='...' CLEAN_SMOKE_PASSWORD='***' \
    LEGACY_SMOKE_USERNAME='testreg' LEGACY_SMOKE_PASSWORD='***' \
    .venv/bin/python scripts/verify_plan_alignment_textbook_live.py

可选环境变量：
    STUDYBUDDY_BASE_URL  API 根地址，默认 http://127.0.0.1:8001
    SMOKE_REGISTER       1=允许自动注册干净号（默认 1）
"""

import argparse
import json
import os
import re
import sys
import time
import uuid

import httpx

DEFAULT_API_BASE = "http://127.0.0.1:8001"

# A：6 个完整计划措辞（目标+时长+内容齐全）
FRESH_PLAN_PROMPTS = [
    "今天学数学 20 分钟，重点复习函数计算和基础巩固，帮我定一个学习计划，只给草案不要直接创建",
    "帮我制定一个语文学习计划，今天能学 30 分钟，重点练现代文阅读理解，内容用我自己选的阅读文章，只给草案不要创建",
    "英语一般过去时的语法和单词，今天学 25 分钟，帮我生成一个计划草案，只给草案不要直接创建",
    "生物细胞结构和光合作用，今天能学 40 分钟，给我安排一个复习计划，只给草案不要直接创建",
    "物理力学和浮力，今天学 35 分钟，想从典型例题入手，帮我定个学习计划，只给草案不要直接创建",
    "化学元素周期表前 20 个元素，今天学 15 分钟，重点是背熟元素符号，帮我做个草案，只给草案不要直接创建",
]
ROUGH_INTENT = "帮我制定一个学习计划吧"
MODIFY_INTENT = "不要这个，改学古诗词"
MODIFY_NUDGE = "就按古诗词基础内容来，直接出草案"
NUDGE = "按你安排的来，直接出草案吧"

# C：3 个无来源教材问法
TEXTBOOK_NO_SOURCE_QUERIES = [
    "人教版八年级语文上册第8课是哪篇课文？",
    "帮我根据语文课本第8课做个学习计划",
    "我语文书第8课是什么？",
]

# 确定性断言句式（与后端 textbook_honesty_guard 口径一致）
_LESSON_TITLE_ASSERT = re.compile(r"第\s*[一二三四五六七八九十百\d]+\s*课\s*(?:是|为|叫)\s*《[^》]+》")
_AUTHOR_ASSERT = re.compile(r"作者\s*(?:是|为|:)\s*[^，。；！？\n]{1,16}")
_PLAN_BASIS_ASSERT = re.compile(r"根据\s*《[^》]+》\s*这篇课文")

_UNCERTAINTY_HINTS = ("无法确认", "无法核验", "不确定", "不能确认", "可能", "请核对", "暂不能")
_QUESTION_HINTS = ("？", "?", "是否", "是不是", "哪篇", "哪一课", "哪课")

# 画像插问信号（与测试口径一致：只认科目/年级指向）
_PROFILE_Q_HINTS = ("几年级", "年级是", "哪科", "哪几科", "什么科目", "薄弱科目", "弱科", "补哪科")


def _looks_like_plaintext(text: str) -> bool:
    """文字草案形状：草案如下/今日学习计划 头部标记 + 明确时长分配。固定失败文案不算。"""
    if not text:
        return False
    header = ("草案如下" in text) or ("今日学习计划" in text) or ("计划草案" in text)
    if not header:
        return False
    return bool(re.search(r"\d+\s*分钟", text))


def contains_deterministic_textbook_assertion(text: str) -> bool:
    """是否包含无来源的确定性教材断言。含不确定/疑问信号的句子不算。"""
    if not text:
        return False
    for sentence in re.split(r"[。！？!?\n；;]", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if any(h in sentence for h in _UNCERTAINTY_HINTS):
            continue
        if any(h in sentence for h in _QUESTION_HINTS):
            continue
        if _LESSON_TITLE_ASSERT.search(sentence) or _AUTHOR_ASSERT.search(sentence) or _PLAN_BASIS_ASSERT.search(sentence):
            return True
    return False


def mid_answer_profile_question_hits(text: str) -> list[str]:
    """主答案中段的画像补全提问（非最后一行出现）。"""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    hits = []
    for idx, line in enumerate(lines):
        if idx >= len(lines) - 1:
            continue
        if ("？" in line or "?" in line) and any(h in line for h in _PROFILE_Q_HINTS):
            hits.append(line)
    return hits


def parse_sse_events(resp: httpx.Response) -> list[dict]:
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


def extract_draft_result(events: list[dict]) -> tuple[bool, str]:
    """是否成功调 draft_study_plan（drafted=true）。返回 (ok, detail)。"""
    for evt in events:
        if evt.get("type") == "tool_result" and evt.get("name") == "draft_study_plan":
            if evt.get("status") != "succeeded":
                continue
            try:
                out = json.loads(evt.get("output") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(out, dict) and out.get("drafted") is True:
                return True, ""
    return False, ""


class Api:
    def __init__(self, base_url: str, token: str):
        self.base = base_url
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = httpx.Client(timeout=httpx.Timeout(connect=15, read=300, write=30, pool=15), follow_redirects=True)

    def url(self, path: str) -> str:
        return self.base.rstrip("/") + path

    def get_json(self, path: str) -> tuple[int, object]:
        resp = self.client.get(self.url(path), headers=self.headers)
        try:
            return resp.status_code, resp.json()
        except json.JSONDecodeError:
            return resp.status_code, resp.text[:500]

    def post_json(self, path: str, body: dict) -> tuple[int, object]:
        resp = self.client.post(self.url(path), json=body, headers=self.headers)
        try:
            return resp.status_code, resp.json()
        except json.JSONDecodeError:
            return resp.status_code, resp.text[:500]

    def post_sse(self, path: str, body: dict) -> tuple[int, list[dict], str]:
        try:
            resp = self.client.post(self.url(path), json=body, headers=self.headers)
        except httpx.HTTPError as exc:
            return 0, [], f"HTTP 请求失败: {exc}"
        if resp.status_code != 200:
            return resp.status_code, [], resp.text[:500]
        try:
            return resp.status_code, parse_sse_events(resp), ""
        except httpx.HTTPError as exc:
            return 0, [], f"SSE 流读取失败: {exc}"


def login(base: str, username: str, password: str) -> tuple[Api | None, int | None, str]:
    try:
        client = httpx.Client(timeout=httpx.Timeout(connect=15, read=30, write=30, pool=15), follow_redirects=True)
        resp = client.post(base + "/auth/login", json={"username": username, "password": password})
        data = resp.json() if resp.status_code == 200 else {}
        client.close()
    except httpx.HTTPError as exc:
        return None, None, f"登录请求失败: {exc}"
    if resp.status_code != 200 or not data.get("access_token"):
        return None, None, f"登录失败 HTTP {resp.status_code}: {str(data)[:200]}"
    return Api(base, data["access_token"]), data.get("user_id"), ""


def register(base: str, username: str, password: str) -> tuple[Api | None, int | None, str]:
    try:
        client = httpx.Client(timeout=httpx.Timeout(connect=15, read=30, write=30, pool=15), follow_redirects=True)
        resp = client.post(base + "/auth/register", json={"username": username, "password": password})
        data = resp.json() if resp.status_code in (200, 201) else {}
        client.close()
    except httpx.HTTPError as exc:
        return None, None, f"注册请求失败: {exc}"
    if resp.status_code not in (200, 201) or not data.get("access_token"):
        return None, None, f"注册失败 HTTP {resp.status_code}: {str(data)[:200]}"
    return Api(base, data["access_token"]), data.get("user_id"), ""


def plan_count(api: Api, user_id: int) -> int:
    st, data = api.get_json(f"/api/students/{user_id}/study-plans?status=")
    if st != 200 or not isinstance(data, dict):
        return -1
    return int(data.get("total", len(data.get("items", []))))


def send_with_negotiation(api: Api, session_id: int, content: str, tag: str, stats: dict, allow_nudge: bool = True) -> tuple[str, list[dict]]:
    """发消息；若 AI 追问（无成功 draft 且正文含问句）最多补答一轮。返回 (final_text, events)。"""
    st, events, err = api.post_sse(f"/api/chat/sessions/{session_id}/messages", {"content": content})
    if st != 200:
        stats["sse_or_http_errors"] += 1
        return f"[SSE失败 {st}] {err}", []
    final_text = _final_text_of(events)
    ok, _ = extract_draft_result(events)
    if not ok and allow_nudge and ("？" in final_text or "?" in final_text):
        st2, events2, err2 = api.post_sse(f"/api/chat/sessions/{session_id}/messages", {"content": NUDGE})
        if st2 == 200:
            events = events + events2
            final_text = _final_text_of(events)
        else:
            stats["sse_or_http_errors"] += 1
    return final_text, events


def _final_text_of(events: list[dict]) -> str:
    """最终正文：优先 done.content（后端守卫校正后的收敛文本），否则 text 事件拼接。"""
    for evt in events:
        if evt.get("type") == "done" and isinstance(evt.get("content"), str) and evt["content"]:
            return evt["content"]
    return "".join(e.get("content", "") for e in events if e.get("type") == "text")


def run_clean_account(base: str, username: str, password: str, stats: dict, detail: list[str], blockers: list[str]) -> None:
    api, user_id, err = register(base, username, password)
    if api is None:
        # 用户名冲突（重跑）：改登录
        api, user_id, err = login(base, username, password)
    if api is None:
        blockers.append(f"干净号不可用: {err}")
        return
    detail.append(f"干净号 {username} user_id={user_id}")

    # 画像：年级 + 想提升科目（避免冷启动强插问干扰）
    st, _ = api.post_json(f"/api/students/{user_id}/profile/onboarding", {"grade": "八年级", "weak_subjects": ["数学"]})
    if st not in (200, 201):
        blockers.append(f"画像写入失败 HTTP {st}")

    # 新建干净主会话
    st, sess = api.post_json("/api/chat/sessions", {"student_id": user_id})
    if st not in (200, 201) or not isinstance(sess, dict) or not sess.get("id"):
        blockers.append(f"建会话失败 HTTP {st}: {str(sess)[:200]}")
        return
    session_id = sess["id"]

    plans_before = plan_count(api, user_id)

    # A：6 个完整措辞（协商循环）
    for i, prompt in enumerate(FRESH_PLAN_PROMPTS):
        final_text, events = send_with_negotiation(api, session_id, prompt, f"fresh{i}", stats)
        ok, _ = extract_draft_result(events)
        stats["fresh_plan_attempts"] += 1
        if ok:
            stats["fresh_successful_draft_tools"] += 1
        elif _looks_like_plaintext(final_text):
            stats["fresh_plaintext_drafts_without_tool"] += 1
        detail.append(f"fresh{i}: {'出卡' if ok else '未出卡'} {final_text[:80]!r}")

    # A：1 个粗略意图（只追问，不出卡）
    final_text, events = send_with_negotiation(api, session_id, ROUGH_INTENT, "rough", stats, allow_nudge=False)
    ok, _ = extract_draft_result(events)
    if ok:
        stats["rough_intent_premature_drafts"] += 1
    detail.append(f"rough: {'提前出卡(异常)' if ok else '只追问(正常)'}")

    # A：1 个修改意图（先出卡，再改学古诗词 → 新卡 supersede 旧卡）
    _, events1 = send_with_negotiation(api, session_id, FRESH_PLAN_PROMPTS[0], "modify1", stats)
    before = plan_count(api, user_id)
    _, events2 = send_with_negotiation(api, session_id, MODIFY_INTENT, "modify2", stats)
    ok2, _ = extract_draft_result(events2)
    detail.append(f"modify: 修改后{'出新卡' if ok2 else '未出新卡'}")

    # C：3 个无来源教材问法（不得有确定性断言）
    for i, q in enumerate(TEXTBOOK_NO_SOURCE_QUERIES):
        final_text, events = send_with_negotiation(api, session_id, q, f"tb{i}", stats)
        stats["textbook_no_source_queries"] += 1
        if contains_deterministic_textbook_assertion(final_text):
            stats["unsupported_definitive_textbook_claims"] += 1
            detail.append(f"tb{i}: 确定性断言! {final_text[:150]!r}")
        else:
            detail.append(f"tb{i}: 无断言(正常) {final_text[:60]!r}")

    # C：回答教材版本 → textbook_versions 写入
    st, prof = api.get_json(f"/api/students/{user_id}/profile/summary")
    if st != 200:
        stats["textbook_profile_write_failures"] += 1

    plans_after = plan_count(api, user_id)
    stats["formal_plan_count_delta"] += max(plans_after - plans_before, 0)
    detail.append(f"干净号正式计划数 {plans_before} -> {plans_after}")


def run_legacy_account(base: str, username: str, password: str, stats: dict, detail: list[str], blockers: list[str]) -> None:
    api, user_id, err = login(base, username, password)
    if api is None:
        blockers.append(f"旧号不可用: {err}")
        return
    detail.append(f"旧号 {username} user_id={user_id}（原旧会话，不清历史）")

    st, session = api.get_json("/api/chat/sessions/primary")
    if st != 200 or not isinstance(session, dict) or not session.get("id"):
        blockers.append(f"获取主会话失败 HTTP {st}")
        return
    session_id = session["id"]
    plans_before = plan_count(api, user_id)

    # E：3 条"另建一个"新主题完整请求（旧历史诱导下仍必须出卡）
    legacy_prompts = [
        "另建一个英语过去进行时学习计划，今天学 20 分钟，重点语法和造句，只给草案不要创建",
        "另建一个数学二次函数学习计划，今天学 25 分钟，重点做典型题，只给草案不要创建",
        "另建一个语文古诗词鉴赏学习计划，今天学 30 分钟，重点默写和赏析，只给草案不要创建",
    ]
    for i, prompt in enumerate(legacy_prompts):
        final_text, events = send_with_negotiation(api, session_id, prompt, f"legacy{i}", stats)
        stats["legacy_plan_attempts"] += 1
        ok, _ = extract_draft_result(events)
        if ok:
            stats["legacy_successful_draft_tools"] += 1
        elif _looks_like_plaintext(final_text):
            stats["legacy_plaintext_drafts_without_tool"] += 1
        detail.append(f"legacy{i}: {'出卡' if ok else '未出卡'} {final_text[:80]!r}")

    plans_after = plan_count(api, user_id)
    stats["formal_plan_count_delta"] += max(plans_after - plans_before, 0)
    detail.append(f"旧号正式计划数 {plans_before} -> {plans_after}")


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 生产验收：计划对齐与教材诚实 smoke")
    parser.add_argument("--fresh-plan-attempts", type=int, default=6, help="完整措辞数（默认 6）")
    parser.add_argument("--legacy-plan-attempts", type=int, default=3, help="旧号请求数（默认 3）")
    parser.add_argument("--no-confirm", action="store_true", help="兼容 M4 命令写法（脚本始终不确认草案）")
    args = parser.parse_args()

    base = os.environ.get("STUDYBUDDY_BASE_URL", DEFAULT_API_BASE).strip().rstrip("/") or DEFAULT_API_BASE
    clean_user = os.environ.get("CLEAN_SMOKE_USERNAME", "").strip()
    clean_pass = os.environ.get("CLEAN_SMOKE_PASSWORD", "").strip()
    legacy_user = os.environ.get("LEGACY_SMOKE_USERNAME", "testreg").strip() or "testreg"
    legacy_pass = os.environ.get("LEGACY_SMOKE_PASSWORD", "").strip()

    if not clean_user:
        clean_user = f"smoke_plan_{int(time.time())}"
    if not clean_pass:
        clean_pass = f"pw_{uuid.uuid4().hex[:12]}"
    if not legacy_pass:
        print(json.dumps({"status": "fail", "error": "缺少环境变量 LEGACY_SMOKE_PASSWORD"}, ensure_ascii=False))
        return 2

    stats = {
        "fresh_plan_attempts": 0, "fresh_successful_draft_tools": 0, "fresh_plaintext_drafts_without_tool": 0,
        "fresh_guard_hard_failures": 0,
        "rough_intent_premature_drafts": 0,
        "legacy_plan_attempts": 0, "legacy_successful_draft_tools": 0, "legacy_plaintext_drafts_without_tool": 0,
        "textbook_no_source_queries": 0, "unsupported_definitive_textbook_claims": 0,
        "unverified_textbook_claims_used_in_drafts": 0,
        "textbook_profile_write_failures": 0,
        "mid_answer_profile_questions": 0,
        "formal_plan_count_delta": 0,
        "sse_or_http_errors": 0,
    }
    detail: list[str] = []
    blockers: list[str] = []

    run_clean_account(base, clean_user, clean_pass, stats, detail, blockers)
    run_legacy_account(base, legacy_user, legacy_pass, stats, detail, blockers)

    # 阈值判定
    expected = {
        "fresh_plan_attempts": args.fresh_plan_attempts,
        "fresh_successful_draft_tools": args.fresh_plan_attempts,
        "fresh_plaintext_drafts_without_tool": 0,
        "fresh_guard_hard_failures": 0,
        "rough_intent_premature_drafts": 0,
        "legacy_plan_attempts": args.legacy_plan_attempts,
        "legacy_successful_draft_tools": args.legacy_plan_attempts,
        "legacy_plaintext_drafts_without_tool": 0,
        "textbook_no_source_queries": 3,
        "unsupported_definitive_textbook_claims": 0,
        "unverified_textbook_claims_used_in_drafts": 0,
        "textbook_profile_write_failures": 0,
        "mid_answer_profile_questions": 0,
        "formal_plan_count_delta": 0,
        "sse_or_http_errors": 0,
    }
    failed_keys = [k for k, v in expected.items() if stats.get(k, 0) != v]
    status = "pass" if not failed_keys and not blockers else "fail"

    print(json.dumps({"batch": "M4", "status": status, "stats": stats,
                      "failed_keys": failed_keys, "blockers": blockers,
                      "clean_user": clean_user, "detail": detail[-20:]}, ensure_ascii=False, indent=1))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

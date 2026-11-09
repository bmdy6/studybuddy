"""Tool Gateway Task1 测试：白名单校验（G3）+ 严格 JSON 解析（G1）。

业界做法：模型失败可预测（prose/code fence/截断/缺字段），服务端确定性兜底。
"""

import asyncio

from app.features.agent.tool_gateway import CircuitBreaker, parse_arguments, run_tool, validate_args

ALLOWED = {"draft_study_plan", "query_study_plans"}


class TestWhiteList:
    def test_unknown_tool_rejected(self):
        """AI 编造工具名：拒绝，可重试（应改用允许的工具）。"""
        r = parse_arguments("create_nothing", "{}", ALLOWED)
        assert not r.ok
        assert r.retryable
        assert "不在可用列表" in r.error

    def test_known_tool_allowed(self):
        r = parse_arguments("draft_study_plan", '{"title":"x"}', ALLOWED)
        assert r.ok
        assert r.data == {"title": "x"}


class TestStrictJson:
    def test_malformed_json_returns_retryable_error(self):
        """畸形 JSON：不再静默降级 args={}，返回可重试错误。"""
        r = parse_arguments("draft_study_plan", "{not json", ALLOWED)
        assert not r.ok
        assert r.retryable
        assert "合法 JSON" in r.error

    def test_empty_arguments_ok(self):
        r = parse_arguments("query_study_plans", "", ALLOWED)
        assert r.ok
        assert r.data == {}

    def test_code_fence_json_stripped(self):
        """模型常用 ```json 包 JSON：剥掉后能解析（业界常见修复）。"""
        r = parse_arguments("draft_study_plan", '```json\n{"title":"x"}\n```', ALLOWED)
        assert r.ok
        assert r.data == {"title": "x"}

    def test_non_object_json_rejected(self):
        """参数必须是 JSON 对象（dict），数组/标量拒绝。"""
        r = parse_arguments("draft_study_plan", "[1,2]", ALLOWED)
        assert not r.ok
        assert r.retryable
        assert "JSON 对象" in r.error


class TestSchemaValidation:
    """Task2：Pydantic schema 校验（G2）——缺必填/类型错返回可重试错误。"""

    def test_missing_required_title(self):
        r = validate_args("draft_study_plan", {"items": [{"title": "x"}]})
        assert not r.ok
        assert r.retryable
        assert "title" in r.error

    def test_empty_items_rejected(self):
        r = validate_args("draft_study_plan", {"title": "x", "items": []})
        assert not r.ok
        assert r.retryable

    def test_minutes_wrong_type(self):
        r = validate_args("draft_study_plan", {"title": "x", "items": [{"title": "t", "minutes": "abc"}]})
        assert not r.ok
        assert r.retryable

    def test_valid_draft_ok(self):
        r = validate_args("draft_study_plan", {"student_id": 2, "title": "x", "items": [{"title": "t", "minutes": 20}]})
        assert r.ok
        assert r.data["title"] == "x"

    def test_create_practice_exam_allows_null_options_for_fill_blank(self):
        r = validate_args(
            "create_practice_exam",
            {
                "title": "填空练习",
                "subject": "english",
                "questions": [
                    {
                        "type": "fill_blank",
                        "stem": "She ___ happy.",
                        "options": None,
                        "answer": "was",
                        "score": 10,
                        "knowledge_tags": ["一般过去时"],
                        "grading": {"rule_type": "auto_fuzzy", "matcher": "levenshtein"},
                    }
                ],
            },
        )
        assert r.ok

    def test_unknown_tool_passes_through(self):
        # 白名单已拦非工具；validate_args 对不在 schema 映射的放行（职责分离）
        r = validate_args("not_a_tool", {"x": 1})
        assert r.ok
        assert r.data == {"x": 1}

    def test_create_plan_requires_confirmed(self):
        r = validate_args("create_study_plan", {"title": "x", "items": [{"title": "t"}]})
        assert not r.ok
        assert r.retryable
        assert "confirmed" in r.error


class TestRunTool:
    """Task3：统一异常结构（G5）——执行异常包装为结构化结果，不吞、如实告知。"""

    def test_success(self):
        async def dispatch(name, args, role, db, tid):
            return {"ok": 1}

        r = asyncio.run(run_tool("query_study_plans", {}, "student", None, 1, dispatch))
        assert r.ok
        assert r.data == {"ok": 1}

    def test_permission_error_structured(self):
        async def dispatch(name, args, role, db, tid):
            raise PermissionError("无权")

        r = asyncio.run(run_tool("x", {}, "student", None, 1, dispatch))
        assert not r.ok
        assert "权限不足" in r.error
        assert not r.retryable

    def test_generic_exception_structured(self):
        async def dispatch(name, args, role, db, tid):
            raise ValueError("boom")

        r = asyncio.run(run_tool("x", {}, "student", None, 1, dispatch))
        assert not r.ok
        assert "工具执行失败" in r.error
        assert not r.retryable


class TestCircuitBreaker:
    """Task4：循环检测熔断（G4）——同一工具连续失败达到阈值即熔断，不再执行。"""

    def test_opens_after_3_consecutive_failures(self):
        cb = CircuitBreaker()
        assert not cb.is_open("draft_study_plan")
        cb.record_failure("draft_study_plan")
        cb.record_failure("draft_study_plan")
        assert not cb.is_open("draft_study_plan")
        cb.record_failure("draft_study_plan")
        assert cb.is_open("draft_study_plan")

    def test_success_resets(self):
        cb = CircuitBreaker()
        cb.record_failure("x")
        cb.record_failure("x")
        cb.record_success("x")
        assert not cb.is_open("x")

    def test_other_tool_unaffected(self):
        cb = CircuitBreaker()
        cb.record_failure("a")
        cb.record_failure("a")
        cb.record_failure("a")
        assert cb.is_open("a")
        assert not cb.is_open("b")

    def test_blocked_tool_not_executed(self):
        """熔断后不执行（dispatch 不被调用），直接返回暂停错误。"""
        cb = CircuitBreaker()
        cb.record_failure("x")
        cb.record_failure("x")
        cb.record_failure("x")
        calls: list[str] = []

        async def spy(name, args, role, db, tid):
            calls.append(name)
            return {}

        r = asyncio.run(run_tool("x", {}, "student", None, 1, spy, cb))
        assert not r.ok
        assert "暂停" in r.error
        assert calls == []

    def test_failures_count_toward_breaker(self):
        async def dispatch(name, args, role, db, tid):
            raise ValueError("boom")

        cb = CircuitBreaker()
        for _ in range(3):
            r = asyncio.run(run_tool("x", {}, "student", None, 1, dispatch, cb))
            assert not r.ok
        assert cb.is_open("x")


class TestSchemaCoverage:
    """Task：input_schema 单一事实源——所有 handler 工具都被网关校验覆盖。"""

    def test_all_handler_tools_covered_by_schema(self):
        from app.features.agent.handlers import _HANDLERS
        from app.features.agent.tool_gateway import _SCHEMA_BY_TOOL

        missing = [n for n in _HANDLERS if n not in _SCHEMA_BY_TOOL]
        assert missing == []

    def test_empty_items_rejected_by_min_items(self):
        """增强后 input_schema 有 minItems，空任务列表被网关拦。"""
        r = validate_args("draft_study_plan", {"title": "x", "items": []})
        assert not r.ok
        assert r.retryable

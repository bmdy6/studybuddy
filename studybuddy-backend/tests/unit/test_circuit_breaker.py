"""ai_service 熔断器单元测试（纯逻辑，不依赖 LLM/DB）。

覆盖：
- 正常调用 → success 计数归零
- 连续失败达阈值 → 熔断 open → 拒绝调用
- 熔断计时到 → half_open → 放一个探测
- 探测成功 → closed 恢复
- 探测失败 → 继续 open
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.ai_service import (
    LLM_CIRCUIT_FAIL_THRESHOLD,
    LLM_CIRCUIT_RESET_SEC,
    CircuitOpenError,
    _CircuitBreaker,
)


class TestCircuitBreaker:
    """熔断器三态转换。"""

    def test_closed_allows_call(self):
        """closed 状态允许调用。"""
        b = _CircuitBreaker()
        b.before_call()  # 不抛异常即通过

    def test_success_resets_fail_count(self):
        """成功后失败计数归零。"""
        b = _CircuitBreaker()
        b.on_failure()
        b.on_failure()
        b.on_success()
        assert b._fail_count == 0
        assert b._state == "closed"

    def test_consecutive_failures_open_circuit(self):
        """连续失败达阈值后熔断。"""
        b = _CircuitBreaker()
        for _ in range(LLM_CIRCUIT_FAIL_THRESHOLD):
            b.on_failure()
        assert b._state == "open"

    def test_open_rejects_call(self):
        """熔断 open 时拒绝调用。"""
        b = _CircuitBreaker()
        for _ in range(LLM_CIRCUIT_FAIL_THRESHOLD):
            b.on_failure()
        with pytest.raises(CircuitOpenError):
            b.before_call()

    def test_open_transitions_to_half_open_after_timeout(self):
        """熔断计时到后转 half_open。"""
        b = _CircuitBreaker()
        for _ in range(LLM_CIRCUIT_FAIL_THRESHOLD):
            b.on_failure()
        assert b._state == "open"
        # 模拟时间过了 reset 周期
        b._opened_at = time.monotonic() - LLM_CIRCUIT_RESET_SEC - 1
        b.before_call()  # 不抛异常 = half_open 放行
        assert b._state == "half_open"

    def test_half_open_success_closes_circuit(self):
        """half_open 探测成功 → closed。"""
        b = _CircuitBreaker()
        for _ in range(LLM_CIRCUIT_FAIL_THRESHOLD):
            b.on_failure()
        b._opened_at = time.monotonic() - LLM_CIRCUIT_RESET_SEC - 1
        b.before_call()  # → half_open
        b.on_success()
        assert b._state == "closed"

    def test_half_open_failure_reopens_circuit(self):
        """half_open 探测失败 → 继续 open。"""
        b = _CircuitBreaker()
        for _ in range(LLM_CIRCUIT_FAIL_THRESHOLD):
            b.on_failure()
        b._opened_at = time.monotonic() - LLM_CIRCUIT_RESET_SEC - 1
        b.before_call()  # → half_open
        b.on_failure()
        assert b._state == "open"

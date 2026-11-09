"""M0 日期硬边界：Agent 域 date_guard 纯函数单测（固定时钟，显式传 today）。

覆盖：
- 空/非法/过去日期 → 今天；今天与合法未来日期保留
- 「今日/今天…（YYYY-MM-DD）」标题末尾括号日期同步为权威 planned_date
- 反例：无「今日/今天」标签、非括号日期、正文历史日期引用不被改写
"""

from datetime import date

from app.config import settings
from app.features.agent import date_guard

TODAY = date(2026, 8, 3)


def test_local_today_returns_date_from_config_timezone():
    # 只依赖 settings.WECHAT_TIMEZONE（config 校验过合法 IANA 时区），返回 date
    assert isinstance(date_guard.local_today(), date)


def test_normalize_planned_date_empty_returns_today():
    assert date_guard.normalize_planned_date(None, TODAY) == "2026-08-03"
    assert date_guard.normalize_planned_date("", TODAY) == "2026-08-03"
    assert date_guard.normalize_planned_date("   ", TODAY) == "2026-08-03"


def test_normalize_planned_date_invalid_returns_today():
    assert date_guard.normalize_planned_date("不是日期", TODAY) == "2026-08-03"
    assert date_guard.normalize_planned_date("2026-13-45", TODAY) == "2026-08-03"
    assert date_guard.normalize_planned_date("08-03", TODAY) == "2026-08-03"


def test_normalize_planned_date_past_returns_today():
    assert date_guard.normalize_planned_date("2026-08-02", TODAY) == "2026-08-03"


def test_normalize_planned_date_today_kept():
    assert date_guard.normalize_planned_date("2026-08-03", TODAY) == "2026-08-03"


def test_normalize_planned_date_future_kept():
    assert date_guard.normalize_planned_date("2026-08-04", TODAY) == "2026-08-04"
    assert date_guard.normalize_planned_date("2026-09-01", TODAY) == "2026-09-01"


def test_sync_title_today_label_full_width_paren():
    title = "今日生物·细胞呼吸补漏（2026-08-02）"
    assert (
        date_guard.sync_today_label_in_title(title, "2026-08-03")
        == "今日生物·细胞呼吸补漏（2026-08-03）"
    )


def test_sync_title_today_label_half_width_paren():
    assert (
        date_guard.sync_today_label_in_title("今天数学(2026-08-02)", "2026-08-03")
        == "今天数学(2026-08-03)"
    )


def test_sync_title_without_today_label_untouched():
    title = "复习计划（2026-08-02）"
    assert date_guard.sync_today_label_in_title(title, "2026-08-03") == title


def test_sync_title_without_trailing_paren_date_untouched():
    title = "今日生物补漏"
    assert date_guard.sync_today_label_in_title(title, "2026-08-03") == title


def test_sync_title_invalid_paren_content_untouched():
    title = "今日计划（下周二）"
    assert date_guard.sync_today_label_in_title(title, "2026-08-03") == title


def test_sync_title_does_not_touch_history_date_in_body():
    # 标题含「今日」但末尾不是括号日期，正文历史日期引用不得被改
    title = "今日复习 2026-07-23 的错题"
    assert date_guard.sync_today_label_in_title(title, "2026-08-03") == title


# ============ M1：当前轮日期锚点 ============


def test_current_date_anchor_contains_server_today_and_timezone():
    anchor = date_guard.current_round_date_anchor()
    assert anchor.startswith("[服务端本轮时间事实：")
    assert date_guard.local_today().isoformat() in anchor
    assert settings.WECHAT_TIMEZONE in anchor


def test_strip_current_round_date_anchor_removes_prefix_only():
    anchored = date_guard.current_round_date_anchor() + "今天安排数学"
    assert date_guard.strip_current_round_date_anchor(anchored) == "今天安排数学"
    # 无锚点的普通内容原样返回
    assert date_guard.strip_current_round_date_anchor("今天安排数学") == "今天安排数学"
    assert date_guard.strip_current_round_date_anchor("") == ""


# ============ M1：最终文本窄范围校正 ============


def test_should_correct_today_label_enabled_only_for_today_intent():
    assert date_guard.should_correct_today_label("今天给我安排学习计划")
    assert date_guard.should_correct_today_label("今日数学")
    assert not date_guard.should_correct_today_label("给我安排学习计划")
    assert not date_guard.should_correct_today_label("2026-07-23 的错题什么时候复习")
    assert not date_guard.should_correct_today_label("")


def test_correct_today_label_replaces_today_is_past_date():
    text = "今天是 2026-08-02，我们开始复习。"
    assert (
        date_guard.correct_today_label_in_text(text, TODAY)
        == "今天是 2026-08-03，我们开始复习。"
    )


def test_correct_today_label_syncs_trailing_paren_date():
    text = "今日生物·细胞呼吸补漏（2026-08-02）。明天继续。"
    assert (
        date_guard.correct_today_label_in_text(text, TODAY)
        == "今日生物·细胞呼吸补漏（2026-08-03）。明天继续。"
    )


def test_correct_today_label_does_not_touch_wrong_question_date():
    # 反例（误伤边界）：今天复习 2026-07-23 的错题 不能被改成今天
    text = "好的，今天复习 2026-07-23 的错题。"
    assert date_guard.correct_today_label_in_text(text, TODAY) == text


def test_correct_today_label_keeps_future_dates():
    # 未来日期不动（不能把未来计划拉回今天）
    assert (
        date_guard.correct_today_label_in_text("今天是 2026-08-10 的安排", TODAY)
        == "今天是 2026-08-10 的安排"
    )
    assert (
        date_guard.correct_today_label_in_text("今日计划（2026-08-10）", TODAY)
        == "今日计划（2026-08-10）"
    )


def test_correct_today_label_keeps_plain_history_dates():
    # 普通日期问答/历史引用不被替换（无今天/今日语义）
    text = "2026-07-23 是周三，复习 2026-07-23 错题。"
    assert date_guard.correct_today_label_in_text(text, TODAY) == text


def test_correct_today_label_keeps_today_date_unchanged():
    # 已经是今天的日期保持幂等
    assert (
        date_guard.correct_today_label_in_text("今天是 2026-08-03", TODAY)
        == "今天是 2026-08-03"
    )
    assert (
        date_guard.correct_today_label_in_text("今日计划（2026-08-03）", TODAY)
        == "今日计划（2026-08-03）"
    )


def test_correct_today_label_handles_empty_text():
    assert date_guard.correct_today_label_in_text("", TODAY) == ""
    assert date_guard.correct_today_label_in_text(None, TODAY) is None

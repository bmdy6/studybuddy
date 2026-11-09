from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

GrowthIntentName = Literal[
    "academic_learning",
    "general_growth",
    "interest_exploration",
    "wellbeing_boundary",
    "system_or_account",
    "unknown",
]
SafetyLevel = Literal["normal", "needs_guardrail", "blocked"]


@dataclass(frozen=True)
class GrowthIntent:
    intent: GrowthIntentName
    confidence: float
    matched_signals: list[str] = field(default_factory=list)
    safety_level: SafetyLevel = "normal"
    strategy_hint: str = ""


SYSTEM_SIGNALS = ["登录", "账号", "密码", "报错", "打不开", "帮助", "连接失败"]
ACADEMIC_SIGNALS = ["数学", "英语", "语文", "错题", "单词", "语法", "作业", "试卷", "阅读理解"]
FITNESS_SIGNALS = ["健身", "跑步", "体能", "力量", "减肥", "运动", "体育"]
GROWTH_SIGNALS = ["口才", "表达", "演讲", "自律", "习惯", "上课回答", "沟通"]
INTEREST_SIGNALS = ["喜欢", "兴趣", "爱好", "想学"]
BLOCKED_RISK_SIGNALS = ["膝盖疼", "疼", "受伤", "药", "极端减肥", "不吃饭", "十公里", "心理危机"]


def _matched(text: str, signals: list[str]) -> list[str]:
    return [signal for signal in signals if signal in text]


def classify_growth_intent(text: str) -> GrowthIntent:
    cleaned = (text or "").strip()
    if not cleaned:
        return GrowthIntent(intent="unknown", confidence=0.0, strategy_hint="没有可判断的输入。")

    system_matches = _matched(cleaned, SYSTEM_SIGNALS)
    if system_matches:
        return GrowthIntent(
            intent="system_or_account",
            confidence=0.9,
            matched_signals=system_matches,
            strategy_hint="这是系统或账号问题，不写入成长目标记忆。",
        )

    risk_matches = _matched(cleaned, BLOCKED_RISK_SIGNALS)
    fitness_matches = _matched(cleaned, FITNESS_SIGNALS)
    growth_matches = _matched(cleaned, GROWTH_SIGNALS)
    academic_matches = _matched(cleaned, ACADEMIC_SIGNALS)

    if risk_matches and (fitness_matches or growth_matches or "跑" in cleaned):
        return GrowthIntent(
            intent="wellbeing_boundary",
            confidence=0.95,
            matched_signals=[*risk_matches, *fitness_matches, *growth_matches],
            safety_level="blocked",
            strategy_hint="涉及疼痛、受伤或高风险训练，不提供训练计划；建议先告诉家长或专业人士。",
        )

    if academic_matches:
        return GrowthIntent(
            intent="academic_learning",
            confidence=0.85,
            matched_signals=academic_matches,
            strategy_hint="这是学科学习请求，继续走现有错题、笔记、素材或学习计划流程。",
        )

    if fitness_matches or growth_matches:
        safety_level: SafetyLevel = "needs_guardrail" if fitness_matches else "normal"
        return GrowthIntent(
            intent="general_growth",
            confidence=0.85,
            matched_signals=[*fitness_matches, *growth_matches],
            safety_level=safety_level,
            strategy_hint="先问目标、场景、可用时间和限制，再给低风险计划草案；学生确认后才创建计划。",
        )

    interest_matches = _matched(cleaned, INTEREST_SIGNALS)
    if interest_matches:
        return GrowthIntent(
            intent="interest_exploration",
            confidence=0.7,
            matched_signals=interest_matches,
            strategy_hint="兴趣由学生自己决定；可以建议尝试路径，但不能要求家长审批兴趣。",
        )

    return GrowthIntent(intent="unknown", confidence=0.2, strategy_hint="未识别到明确成长目标。")


def build_growth_strategy_context(text: str) -> str:
    intent = classify_growth_intent(text)
    if intent.intent in {"academic_learning", "system_or_account", "unknown"}:
        return ""

    if intent.intent == "wellbeing_boundary":
        return (
            "\n[成长目标策略] 当前输入涉及身体疼痛、受伤或高风险训练。"
            "不要给训练计划、医疗建议或极端方案；先建议学生告诉家长，必要时咨询专业人士。"
            "如果后续要制定低风险习惯计划，也必须先给计划草案并等待学生明确确认。"
        )

    if intent.intent == "interest_exploration":
        return (
            "\n[成长目标策略] 当前输入更像兴趣探索。兴趣属于学生自己，家长不审批兴趣。"
            "可以先问学生为什么感兴趣、想尝试到什么程度、每周能投入多久；"
            "需要沉淀兴趣或计划时，先给草案，确认后再保存或创建。"
        )

    return (
        "\n[成长目标策略] 当前输入是非学科成长目标。先问目标、使用场景、可用时间和限制，"
        "不要直接创建计划。若给建议，只给低风险、短任务的计划草案，并询问是否可行；"
        "只有学生明确确认后，才能调用 create_study_plan 且 confirmed=true。"
        f"分类依据：{', '.join(intent.matched_signals)}。"
    )

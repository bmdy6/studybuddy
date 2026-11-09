from app.features.growth.intent_service import build_growth_strategy_context, classify_growth_intent


def test_classifies_speech_training_as_general_growth():
    result = classify_growth_intent("我想练口才，上课回答问题更清楚")

    assert result.intent == "general_growth"
    assert result.safety_level == "normal"
    assert "口才" in result.matched_signals


def test_classifies_fitness_as_growth_with_guardrail():
    result = classify_growth_intent("我要健身，每天练一下")

    assert result.intent == "general_growth"
    assert result.safety_level == "needs_guardrail"
    assert "健身" in result.matched_signals


def test_blocks_painful_high_risk_fitness_plan():
    result = classify_growth_intent("我膝盖疼还想每天跑十公里")

    assert result.intent == "wellbeing_boundary"
    assert result.safety_level == "blocked"
    assert "膝盖疼" in result.matched_signals


def test_keeps_academic_learning_separate():
    result = classify_growth_intent("我今天想背英语单词")

    assert result.intent == "academic_learning"
    assert result.safety_level == "normal"


def test_system_questions_do_not_trigger_growth_memory():
    result = classify_growth_intent("登录失败了怎么办")

    assert result.intent == "system_or_account"
    assert result.safety_level == "normal"


def test_strategy_context_for_growth_requires_draft_confirmation():
    context = build_growth_strategy_context("我想练口才")

    assert "[成长目标策略]" in context
    assert "先问目标" in context
    assert "计划草案" in context
    assert "确认" in context


def test_strategy_context_empty_for_system_question():
    assert build_growth_strategy_context("怎么登录") == ""

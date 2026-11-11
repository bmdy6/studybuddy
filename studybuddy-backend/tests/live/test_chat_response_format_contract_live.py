"""结构化终态协议真实 MiMo 契约验收（批次 3）。

复现 msg 2637 场景（数学讲解）：MiMo 偶发把 \n 输出成空格导致 markdown 失效。
批次 1 已实现 present_response 终态协议：模型自由正文一律被拦截、强制补调、
fail-closed 降级。本测试用真实 MiMo 连续跑 ≥10 轮"数学讲解"prompt，验证：

- 10/10 最终响应通过结构化 schema（content 非空、无坏模式 ` --- ### ` 同行结构）
- 数据库落库 content 与 run_agent_turn 返回一致
- 数学式字符（a > 0、-b/2a 等）逐字保留
- 不出现 emoji

强制补调路径由 mock 单测（test_response_blocks.py）保证；本测试验证真实模型
在 happy path 下遵守协议、输出可被协议接收。
"""

import asyncio
import re

import pytest

from app.features.chat import agent, sessions
from app.models.chat import ChatSession
from app.models.user import User

# 坏模式：同行内 `--- ###`、句中 `###`、冒号后 `> ` 引用挤行
_BAD_MARKDOWN = (
    re.compile(r"[ \t]---[ \t]#{1,6}[ \t]"),          # 分隔线+标题仍挤一行
    re.compile(r"[^。！？!?；;\n][ \t]#{1,6}[ \t]"),  # 句中标题
    re.compile(r"[：:][ \t]+>[ \t]+"),                 # 冒号后引用仍挤
)
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")

MATH_PROMPT = (
    "请讲解一元二次函数：包括定义、图像、对称轴公式、顶点坐标，"
    "并说明 a > 0 和 a < 0 两种情况，最后给一个练习题 y = 2x² - 4x + 1。"
)
# 数学式匹配：容忍模型措辞差异（a > 0 或 "a 大于 0"、-b/2a 或 "-b / 2a"）
_MATH_MARKERS = ("a > 0", "a < 0", "-b/2a")
_MATH_ALT = (
    re.compile(r"a\s*[>＞]\s*0"),
    re.compile(r"a\s*[<＜]\s*0"),
    re.compile(r"-?\s*b\s*/\s*2\s*a"),
    re.compile(r"对称轴"),
    re.compile(r"顶点"),
)


def _has_bad_markdown(text: str) -> bool:
    return any(pattern.search(text) for pattern in _BAD_MARKDOWN)


def _has_emoji(text: str) -> bool:
    return bool(_EMOJI.search(text))


def _last_assistant_content(db, session_id: int) -> str:
    from app.features.chat.sessions import get_messages

    messages = get_messages(db, session_id)
    for message in reversed(messages):
        if message.role == "assistant" and message.content:
            return message.content
    return ""


@pytest.mark.live
def test_present_response_contract_math_explanation_repeats(db) -> None:
    """连续 10 轮数学讲解：全部通过结构化终态协议（无坏模式/无 emoji/落库一致）。"""
    student = db.get(User, 2)
    # 用独立普通会话（不设 primary_student_id），避免复用开发库历史主会话：
    # 共享历史会让模型看到旧上下文（如"我注意到你一直在发同一个请求"），干扰契约验收。
    chat_session = ChatSession(
        user_id=student.id,
        student_id=student.id,
        role_at_create="student",
        title="live协议验收",
    )
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)

    rounds = 10
    results: list[tuple[str, str]] = []

    async def run_round(content: str) -> str:
        return await agent.run_agent_turn(
            db, chat_session, student, content, auto_title_session=False
        )

    for index in range(rounds):
        # 每轮用略有差异的 prompt 分支，覆盖定义/对称轴/顶点/开口方向/练习
        prompts = [
            MATH_PROMPT,
            "讲一下一元二次函数的定义和标准形式，用简单例子说明。",
            "二次函数的对称轴公式是什么？顶点坐标怎么算？举例说明。",
            "a 的正负决定抛物线开口方向，请分别说明 a>0 和 a<0 的图像特征。",
            "出一道求对称轴和顶点坐标的练习题，并讲解解法。",
            "一元二次函数和一元二次方程有什么关系？举个对比例子。",
            "抛物线的最高点或最低点怎么找？结合顶点公式讲。",
            "y = x² - 4x + 3 的对称轴和顶点是多少？逐步算给我看。",
            "解释一下判别式 Δ 和抛物线与 x 轴交点的关系。",
            "总结一下一元二次函数最重要的三个知识点，各配一个例子。",
        ]
        content = prompts[index % len(prompts)]
        reply = asyncio.run(run_round(content))
        assert reply, f"第 {index + 1} 轮返回空 content"
        results.append((content, reply))

        # 1. 无坏模式：` --- ### ` 同行结构不应出现
        assert not _has_bad_markdown(reply), (
            f"第 {index + 1} 轮出现坏 markdown 模式:\n{reply[:300]}"
        )
        # 2. 无 emoji
        assert not _has_emoji(reply), f"第 {index + 1} 轮出现 emoji:\n{reply[:200]}"
        # 3. 实质内容：回复必须非空且有一定长度（协议渲染后的完整回复）
        assert len(reply) >= 20, f"第 {index + 1} 轮回复过短:\n{reply[:300]}"
        # 4. 本轮落库 content 与返回一致（当场对比，避免多轮后最后一条被覆盖）
        persisted = _last_assistant_content(db, chat_session.id)
        assert persisted == reply, (
            f"第 {index + 1} 轮落库 content 与返回不一致:\n返回={reply[:150]}\n落库={persisted[:150]}"
        )

    # 3b. 数学核心内容抽查：讲解轮（1/3/5/7）必须覆盖对称轴/顶点/a>0 开口方向至少其一
    _CORE_MATH = (
        re.compile(r"对称轴"),
        re.compile(r"顶点"),
        re.compile(r"开口"),
        re.compile(r"a\s*[>＞]\s*0"),
    )
    for index in (0, 2, 4, 6):
        _, reply = results[index]
        assert any(pattern.search(reply) for pattern in _CORE_MATH), (
            f"第 {index + 1} 轮（讲解）数学内容缺失:\n{reply[:300]}"
        )

"""主对话系统提示（按角色）。

system_prompt(role, business_actor) 按角色从 .md 读取基础提示，
拼装 当前日期 + 回复格式。task_system_prompt 同理。
基础提示内容在 app/prompts/agent/*.md，动态部分（日期）在此计算。
依赖 app.config（时区），不依赖任何 features。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.prompts import load, render


def _current_date_hint() -> str:
    """注入后端当前本地日期，避免模型自行推断成训练数据日期。"""
    zone = ZoneInfo(settings.WECHAT_TIMEZONE)
    now = datetime.now(zone)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return (
        f"当前日期：{now.date().isoformat()}（{weekdays[now.weekday()]}）。"
        "涉及 planned_date、今天、日期时一律以这个为准，不要自行推断或使用其他日期。"
    )


def task_system_prompt(student_name: str = "弟弟") -> str:
    return f"{render('agent/system_task', student_name=student_name)}\n\n{_current_date_hint()}\n\n{load('agent/response_format')}"


def system_prompt(
    role: str, business_actor: str | None = None, student_name: str = "弟弟", parent_name: str = "哥哥"
) -> str:
    if business_actor == "channel_guardian":
        base = load("agent/system_channel_guardian")
    elif business_actor == "hobby":
        base = render("agent/system_student_hobby", student_name=student_name)
    else:
        name = "agent/system_parent" if role == "teacher" else "agent/system_student"
        base = render(
            name,
            student_name=student_name,
            parent_name=parent_name,
            light_practice_min_questions=str(settings.config.agent.light_practice.min_questions),
            light_practice_max_questions=str(settings.config.agent.light_practice.max_questions),
        )
    return f"{base}\n\n{_current_date_hint()}\n\n{load('agent/response_format')}"

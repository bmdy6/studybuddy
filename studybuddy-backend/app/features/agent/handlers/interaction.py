"""Agent 通用展示型交互工具处理器。

present_choice_question：画像以外的有限选项选择题（计划协商/任务执行/试卷选择），
纯展示不落库，把 question/options/allow_other 回显给前端渲染成可点按钮。
依赖方向：无外部依赖（纯回显），是 agent 域最稳定的展示子模块。
"""
from typing import Any

from sqlalchemy.orm import Session


async def _handle_present_choice_question(
    args: dict[str, Any], role: str, db: Session, teacher_id: int
) -> dict[str, Any]:
    """展示型工具：把有限选项问题交给前端渲染成可点按钮。不落库，只回显供 agent 组织提问文本。

    与 present_profile_question 的区别：本工具不绑画像语义（无 field、不接 update_profile），
    服务于画像以外的任何 2-4 选项决策（计划/任务/试卷）。allow_other 默认 true，
    给学生「都不符合，自己输入」兜底。
    """
    question = args.get("question") or ""
    raw_options = args.get("options") or []
    # 校验 + 规整：options 必须是对象列表且各有 label/value，value 去重防前端 React key 冲突
    options: list[dict[str, Any]] = []
    seen_values: set[str] = set()
    for opt in raw_options:
        if not isinstance(opt, dict):
            continue
        label = (opt.get("label") or "").strip()
        value = (opt.get("value") or "").strip()
        if not label or not value or value in seen_values:
            continue
        seen_values.add(value)
        item: dict[str, Any] = {"label": label[:40], "value": value[:40]}
        # 透传前端动作标记（action=return_to_main 用于计划会话跑题引导学生回主会话建新计划）
        action = opt.get("action")
        if isinstance(action, str) and action in ("return_to_main",):
            item["action"] = action
            prefill = opt.get("prefill")
            if isinstance(prefill, str) and prefill.strip():
                item["prefill"] = prefill.strip()[:100]
        options.append(item)
    if len(options) < 2:
        return {"error": "present_choice_question 需至少 2 个有效选项（label+value 唯一）"}
    # 通用选择题始终提供「其他」自定义项，不依赖 AI 是否传 allow_other
    allow_other = True
    return {
        "asked": True,
        "question": question,
        "options": options,
        "allow_other": allow_other,
        "next_step": "question 和选项已由前端卡片展示；正文不要重复 question 文本或选项，等待学生选择后继续。",
    }

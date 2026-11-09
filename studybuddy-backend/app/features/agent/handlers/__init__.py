"""Agent 工具处理器注册表。

拆自 app/core/agent_loop.py。_HANDLERS 把工具名映射到 _handle_* 协程，agent_loop._dispatch
据此分发。按业务域拆 4 子模块（exam/learning/profile/material），本 __init__ 聚合注册表
并 re-export 全部 _handle_*，供 agent_loop 主模块 facade 访问（test 经 agent_loop._handle_X
直接调用 handler 验证真实行为，故需经 agent_loop 再导出）。
"""
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from .exam import (
    _can_access_exam_batch,
    _get_exam_batch_photo_paths,
    _handle_create_exam,
    _handle_create_practice_exam,
    _handle_grade_light_answer,
    _handle_grade_homework_photo,
    _handle_import_errors_grade,
    _handle_import_errors_process,
    _handle_query_error_book,
    _handle_query_practice_exam_result,
    _handle_recognize_homework_photo_markdown,
    _handle_save_graded_homework_errors,
    _load_exam_batch_photos,
)
from .learning import (
    _handle_archive_study_plan,
    _handle_bilibili_course_assist,
    _handle_complete_task_item,
    _handle_create_study_plan,
    _handle_draft_study_plan,
    _handle_query_diagnosis,
    _handle_query_feedback,
    _handle_query_learning_map,
    _handle_query_notes,
    _handle_query_recommendations,
    _handle_query_study_plans,
    _handle_record_feedback,
    _handle_recommend_resource,
    _handle_search_resource,
    _handle_save_note,
    _handle_search_paper_sources,
    _handle_update_study_plan,
)
from .material import (
    _dedupe_keep_order,
    _handle_list_materials,
    _handle_read_material,
    _suggest_material_metadata,
)
from .profile import (
    _handle_get_attributes,
    _handle_init_attributes,
    _handle_present_profile_question,
    _handle_record_interest,
    _handle_save_profile_onboarding,
    _handle_update_attributes,
    _handle_update_profile,
)
from .interaction import _handle_present_choice_question

# 工具注册器：name -> handler 协程。ALL_TOOLS(tools.py) 的 name 必须与此处 key 一一对应
# （test_agent_loop.TestToolRegistry.test_all_tools_have_handlers 校验）。
_HANDLERS: dict[str, Callable[[dict, str, Session, int], Awaitable[Any]]] = {
    "create_exam": _handle_create_exam,
    "create_practice_exam": _handle_create_practice_exam,
    "grade_light_answer": _handle_grade_light_answer,
    "query_diagnosis": _handle_query_diagnosis,
    "query_learning_map": _handle_query_learning_map,
    "query_error_book": _handle_query_error_book,
    "query_practice_exam_result": _handle_query_practice_exam_result,
    "recommend_resource": _handle_recommend_resource,
    "search_hobby_resource": _handle_search_resource,
    "bilibili_course_assist": _handle_bilibili_course_assist,
    "search_paper_sources": _handle_search_paper_sources,
    "record_feedback": _handle_record_feedback,
    "create_study_plan": _handle_create_study_plan,
    "draft_study_plan": _handle_draft_study_plan,
    "query_study_plans": _handle_query_study_plans,
    "archive_study_plan": _handle_archive_study_plan,
    "update_study_plan": _handle_update_study_plan,
    "complete_task_item": _handle_complete_task_item,
    "get_attributes": _handle_get_attributes,
    "save_profile_onboarding": _handle_save_profile_onboarding,
    "init_attributes": _handle_init_attributes,
    "save_note": _handle_save_note,
    "import_errors_process": _handle_import_errors_process,
    "import_errors_grade": _handle_import_errors_grade,
    "recognize_homework_photo_markdown": _handle_recognize_homework_photo_markdown,
    "grade_homework_photo": _handle_grade_homework_photo,
    "save_graded_homework_errors": _handle_save_graded_homework_errors,
    "record_interest": _handle_record_interest,
    "update_attributes": _handle_update_attributes,
    "update_profile": _handle_update_profile,
    "present_profile_question": _handle_present_profile_question,
    "present_choice_question": _handle_present_choice_question,
    "read_material": _handle_read_material,
    "list_materials": _handle_list_materials,
    "query_notes": _handle_query_notes,
    "query_feedback": _handle_query_feedback,
    "query_recommendations": _handle_query_recommendations,
}

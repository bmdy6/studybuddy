"""Agent 工具注册表（Anthropic 格式 schema + 角色可见集）。

拆自 app/core/agent_loop.py。28 个 _TOOL_* schema 定义 + ALL_TOOLS/TEACHER_TOOLS/
STUDENT_TOOLS/CHANNEL_GUARDIAN_TOOLS 角色可见集 + tools_for_role/tools_for_actor 选择器。
tools_for_actor 是 agent_loop 主循环决定本轮可用工具的入口。
无业务依赖（纯数据/逻辑）。
"""
from typing import Any

from app.config import settings

# ---- 工具定义（Anthropic 格式：name + description + input_schema） ----

# 科目枚举唯一来源：config.yaml agent.practice_exam.subject_codes（协议契约，新增科目需同步能力）
_SUBJECT_CODES = list(settings.config.agent.practice_exam.subject_codes)

_TOOL_CREATE_EXAM = {
    "name": "create_exam",
    "description": (
        "生成一套试卷并落库，弟弟立即可见。"
        "questions 每题需含 type/stem/options(选择题)/answer/score/knowledge_tags/grading。"
        "grading.rule_type: auto_exact(精确匹配)/auto_fuzzy(模糊)/manual(主观人工批改)。"
        "grading.matcher: exact/regex/float_tol/levenshtein。"
        "answer: 选择题传选项索引数组如[0,2]，填空传字符串，主观传参考答案文本。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "试卷标题，如「英语 U5 定语从句练习」"},
            "subject": {"type": "string", "enum": _SUBJECT_CODES},
            "feedback_mode": {"type": "string", "enum": ["immediate", "after_submit", "hidden"], "default": "after_submit"},
            "questions": {
                "type": "array",
                "description": "题目列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["single_choice", "multi_choice", "fill_blank", "transform", "translation", "essay", "math_answer"],
                        },
                        "stem": {"type": "string", "description": "题干"},
                        "options": {"type": "array", "items": {"type": "string"}, "description": "选择题选项，非选择题留空"},
                        "answer": {"description": "标准答案，选择题传选项索引数组如[0,2]，填空传字符串，主观传参考答案"},
                        "score": {"type": "number", "description": "分值，>0"},
                        "knowledge_tags": {"type": "array", "items": {"type": "string"}, "description": "知识点标签如['定语从句','U5']"},
                        "group_id": {"type": "string", "description": "题组标识，可选"},
                        "grading": {
                            "type": "object",
                            "properties": {
                                "rule_type": {"type": "string", "enum": ["auto_exact", "auto_fuzzy", "manual"]},
                                "matcher": {"type": "string", "enum": ["exact", "regex", "float_tol", "levenshtein"]},
                                "match_params": {"type": "object"},
                            },
                            "required": ["rule_type", "matcher"],
                        },
                    },
                    "required": ["type", "stem", "answer", "score", "knowledge_tags", "grading"],
                },
            },
        },
        "required": ["title", "subject", "questions"],
    },
}


_TOOL_CREATE_PRACTICE_EXAM = {
    "name": "create_practice_exam",
    "description": (
        "为学生生成一套自练卷并自动分发给他自己，弟弟点开就能做。"
        "用于计划项需要专项练习或弟弟主动要求练手时。"
        "questions 每题需含 type/stem/options(选择题)/answer/score/knowledge_tags/grading。"
        "feedback_mode 自练默认 immediate（做完一题立即对错）。"
        "plan_item_id 可选：为某计划项出专项练习时传，纯自练不传。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "试卷标题，如「一般过去时专项练习」"},
            "subject": {"type": "string", "enum": _SUBJECT_CODES},
            "feedback_mode": {"type": "string", "enum": ["immediate", "after_submit", "hidden"], "default": "immediate"},
            "plan_item_id": {"type": "integer", "description": "关联的学习计划项 id，纯自练不传"},
            "questions": {
                "type": "array",
                "description": "题目列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["single_choice", "multi_choice", "fill_blank", "transform", "translation", "essay", "math_answer"],
                        },
                        "stem": {"type": "string", "description": "题干"},
                        "options": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "null"},
                            ],
                            "description": "选择题选项，非选择题可传 null 或空数组",
                        },
                        "answer": {"description": "标准答案，选择题传选项索引数组如[0,2]，填空传字符串，主观传参考答案"},
                        "score": {"type": "number", "description": "分值，>0"},
                        "knowledge_tags": {"type": "array", "items": {"type": "string"}, "description": "知识点标签"},
                        "group_id": {"type": "string", "description": "题组标识，可选"},
                        "grading": {
                            "type": "object",
                            "properties": {
                                "rule_type": {"type": "string", "enum": ["auto_exact", "auto_fuzzy", "manual"]},
                                "matcher": {"type": "string", "enum": ["exact", "regex", "float_tol", "levenshtein"]},
                                "match_params": {"type": "object"},
                            },
                            "required": ["rule_type", "matcher"],
                        },
                    },
                    "required": ["type", "stem", "answer", "score", "knowledge_tags", "grading"],
                },
            },
        },
        "required": ["title", "subject", "questions"],
    },
}


_TOOL_QUERY_PRACTICE_EXAM_RESULT = {
    "name": "query_practice_exam_result",
    "description": (
        "查询当前计划项最近一次已正式提交的自练卷逐题结果。"
        "学生完成计划内自练卷、要求复盘或准备完成任务时必须先调用；"
        "只能依据返回的正式作答、正确答案和判分解释错因，不得要求学生重复输入整套答案。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan_item_id": {"type": "integer", "description": "当前学习计划项 id"},
        },
        "required": ["plan_item_id"],
    },
}


_TOOL_QUERY_DIAGNOSIS = {
    "name": "query_diagnosis",
    "description": "查询学生的学情诊断：薄弱知识点 TopN、已掌握标签。了解弟弟哪里薄弱以便针对性出题。",
    "input_schema": {
        "type": "object",
        "properties": {"student_id": {"type": "integer"}, "top_n": {"type": "integer", "default": 10}},
        "required": ["student_id"],
    },
}

_TOOL_QUERY_LEARNING_MAP = {
    "name": "query_learning_map",
    "description": (
        "查询学生学习地图：按知识点聚合错题次数、复盘笔记、已确认素材和计划反馈。"
        "当用户问「我最近最该补什么」「学习地图」「哪些知识点薄弱」「错题和笔记整体情况」时优先调用。"
        "返回的状态 weak/reviewing/stable/unknown 分别表示需要优先补、正在巩固、基本稳定、资料已沉淀但掌握度待验证。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "limit": {"type": "integer", "description": "最多返回多少个知识点，默认 10，最大 30"},
        },
        "required": ["student_id"],
    },
}

_TOOL_QUERY_ERROR_BOOK = {
    "name": "query_error_book",
    "description": "查询学生错题本，可按学科过滤，用于讲解错题或针对性出题。",
    "input_schema": {
        "type": "object",
        "properties": {"student_id": {"type": "integer"}, "subject": {"type": "string"}},
        "required": ["student_id"],
    },
}

_TOOL_RECOMMEND_RESOURCE = {
    "name": "recommend_resource",
    "description": (
        "根据学生薄弱点/兴趣推荐 B站学习视频。"
        "你只需提供搜索关键词（如「英语不规则动词过去式 讲解」），"
        "后端会搜 B站返回 Top3 具体视频（含BV号/标题/UP主/播放量/链接/简介/弹幕采样），并自动落库播放量最高的一个。"
        "返回的候选带简介和弹幕采样——你要据此判断内容是否匹配需求："
        "简介说的是不是这个知识点？弹幕有没有'讲得好''没懂'等反馈？过滤明显不合适的（如娱乐向）。"
        "在回复里推荐 1-2 个并说明判断理由。不要自己编造 URL 或给搜索页链接。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "keyword": {"type": "string", "description": "B站搜索关键词，尽量精确如「英语 不规则动词 讲解」"},
            "reason": {"type": "string", "description": "推荐理由（结合学生薄弱点/兴趣）"},
            "related_interests": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["student_id", "keyword"],
    },
}

_TOOL_SEARCH_RESOURCE = {
    "name": "search_hobby_resource",
    "description": (
        "搜 B站真实学习资源（唱歌/乐器/配音/口语等兴趣教程）。"
        "你只需提供搜索关键词（如「唱歌 气息练习 教程」），后端会真实搜 B站返回 Top 视频"
        "（含标题/UP主/播放量/链接/简介/弹幕采样）。"
        "返回的候选带简介和弹幕采样——你要据此判断内容是否匹配用户兴趣，过滤明显不合适的"
        "（如娱乐向、无关内容）。在回复里推荐 1-2 个并说明理由，必须给出完整可点击链接。"
        "不要编造 URL 或给搜索页链接。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "B站搜索关键词，尽量精确如「唱歌 气息练习 教程」",
            },
            "reason": {
                "type": "string",
                "description": "推荐理由（结合用户想学的兴趣）",
            },
        },
        "required": ["keyword"],
    },
}

_TOOL_BILIBILI_COURSE_ASSIST = {
    "name": "bilibili_course_assist",
    "description": (
        "B站学习助手：帮弟弟从 B站合集课程里定位该学哪一集，并感知单集内容。三种用法："
        "1) 合集目录：传 url（https://www.bilibili.com/video/BVxxx 或裸 BV 号）返回合集全集目录"
        "（每集标题/时长/直链）；2) 选集推荐：结合 weak_points（薄弱点）/focus（关注点）判断该看第几集，"
        "把该集直链给弟弟；3) 单集内容感知：url + read_content=true 读取该集字幕或音频转写内容，"
        "确认这一集具体讲什么、是否匹配需求。另有 keyword 用法：传关键词返回 Top3 候选视频"
        "（含简介/弹幕采样）供筛选。本工具不落库、不计入任何统计。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "B站视频链接或 BV 号，如 https://www.bilibili.com/video/BV1pw411p7ig 或 BV1pw411p7ig"},
            "keyword": {"type": "string", "description": "搜索关键词，与 url 二选一；返回 Top3 候选视频（含简介/弹幕采样）"},
            "weak_points": {"type": "string", "description": "学生薄弱点，供判断该看哪一集，可选"},
            "focus": {"type": "string", "description": "本次关注点，供判断该看哪一集，可选"},
            "read_content": {"type": "boolean", "description": "true 时读取单集内容（字幕/音频转写），需同时传 url"},
        },
    },
}

_TOOL_SEARCH_PAPER_SOURCES = {
    "name": "search_paper_sources",
    "description": (
        "搜索并保存本地化试卷候选来源，用于项目级终极题库建设。"
        "当用户想找某学校/区县/年级/学科的近几年期中期末卷、真题、统考卷时调用。"
        "工具会生成搜索关键词、抓取公开搜索结果、保存候选来源，并给每个来源标记可获得性等级和风险等级。"
        "注意：这只是候选来源采集，不代表已经解析成题目；C类资源可作为内部候选/风格库，D类表示只保留搜索入口。"
        "此工具仅用于题库建库采集公开试卷来源，不用于给学生取学习素材/单词表/课文等即时学习资料；"
        "学生要的学习资料请引导他自行上传素材，不要暗示你能替他抓取网页内容。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "province": {"type": "string", "description": "省份，如 江苏"},
            "city": {"type": "string", "description": "城市，如 苏州"},
            "district": {"type": "string", "description": "区县，如 苏州工业园区"},
            "school": {"type": "string", "description": "学校名，如 示例学校"},
            "grade": {"type": "string", "description": "年级，如 七年级/初一"},
            "semester": {"type": "string", "description": "学期/册次，如 七年级下册/上学期"},
            "subject": {"type": "string", "description": "学科，如 数学/英语"},
            "textbook_version": {"type": "string", "description": "教材版本，可选"},
            "exam_type": {"type": "string", "description": "考试类型，如 期中/期末/月考/统考"},
            "year": {"type": "integer", "description": "年份，可选"},
            "limit": {"type": "integer", "description": "候选数量，默认8，最多20"},
        },
        "required": ["grade", "subject"],
    },
}

_TOOL_RECORD_FEEDBACK = {
    "name": "record_feedback",
    "description": "记录学生的学习反馈（时长/资源观看/自评/困难）。仅学生可用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "feedback_type": {"type": "string", "enum": ["duration", "resource_view", "self_assess", "difficulty"]},
            "content": {"type": "string", "description": "反馈内容"},
        },
        "required": ["student_id", "feedback_type", "content"],
    },
}

_TOOL_CREATE_STUDY_PLAN = {
    "name": "create_study_plan",
    "description": (
        "在用户已经确认计划草案后，创建学习计划并落库。"
        "禁止在用户只表达粗略意图时直接调用；必须先协商目标、可用时长、内容偏好，并得到明确确认。"
        "计划要结合已查询到的学情/错题/兴趣/近期错因反馈；如果还没查，先调用 query_diagnosis/query_error_book/query_feedback/query_notes 等工具。"
        "调用时必须传 confirmed=true；planned_date 不确定时传今天。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "title": {"type": "string", "minLength": 1, "description": "计划标题，如「今晚英语时态补漏」"},
            "focus": {"type": "string", "description": "计划目标/关注点"},
            "description": {"type": "string", "description": "计划完整说明：必须填。写清协商依据（参考了什么学情/错题、学生目标、为什么这么拆任务），后续任务会话靠这个带上下文，不能只写标题或留空"},
            "context_refs": {"type": "object", "description": "来源上下文引用（如错题 id/素材 id），可选"},
            "planned_date": {"type": "string", "description": "计划日期 YYYY-MM-DD，可选"},
            "confirmed": {"type": "boolean", "description": "用户已明确确认该计划草案可行后传 true"},
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "任务标题"},
                        "target": {"type": "string", "description": "完成标准/督促口径"},
                        "minutes": {"type": "integer", "description": "建议用时，5-60 分钟"},
                        "related_tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["student_id", "title", "items", "confirmed"],
    },
}

_TOOL_DRAFT_STUDY_PLAN = {
    "name": "draft_study_plan",
    "description": (
        "这是生成可确认计划草案的唯一入口。只要你准备向学生给出包含任务、时长的计划草案，"
        "必须调用本工具，禁止把同样内容写在正文里。只有返回 drafted=true 才算草案成功；"
        "失败时不得用文字草案替代。"
        "不要让学生用文字'可以/嗯/行'确认——必须等前端卡片确认事件。"
        "计划要结合已查询到的学情/错题/兴趣/近期错因反馈；如果还没查，先调用 query_diagnosis/query_error_book/query_feedback/query_notes 等工具。"
        "planned_date 不确定时传今天。"
        "计划引用具体课名、作者或课文内容时，description 必须说明依据："
        "「学生本轮明确提供……」或「用户上传素材 material_id=...」。"
        "只有教材版本、没有内容来源时，禁止补具体课名；可写中性「课本第 X 课」并说明尚未核验。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "title": {"type": "string", "minLength": 1, "description": "计划标题，如「今晚英语时态补漏」"},
            "focus": {"type": "string", "description": "计划目标/关注点"},
            "description": {"type": "string", "description": "计划完整说明：写清协商依据（参考了什么学情/错题、学生目标、为什么这么拆任务）"},
            "planned_date": {"type": "string", "description": "计划日期 YYYY-MM-DD，可选"},
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "任务标题"},
                        "target": {"type": "string", "description": "完成标准/督促口径"},
                        "minutes": {"type": "integer", "description": "建议用时，5-60 分钟"},
                        "related_tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["student_id", "title", "items"],
    },
}

_TOOL_QUERY_STUDY_PLANS = {
    "name": "query_study_plans",
    "description": (
        "查询学生的学习计划，默认返回当前计划；学生查询历史计划时必须传 topic，并把 status 传空字符串以返回全部计划（包括已归档），用于检查是否有可沿用的历史计划。"
        "返回的 as_of_date 是服务端当前日期；每项计划的 overdue_days/is_overdue/reminders 由服务端按该日期计算。"
        "逾期天数必须直接引用返回的 overdue_days，不得根据聊天历史自行计算或口算日期差。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "status": {"type": "string", "default": "active", "description": "传空字符串查全部计划，包括已归档计划"},
            "topic": {"type": "string", "description": "学生查询历史计划时必填：当前想学习的科目或板块"},
        },
        "required": ["student_id"],
    },
}

_TOOL_ARCHIVE_STUDY_PLAN = {
    "name": "archive_study_plan",
    "description": (
        "在学生或家长明确确认后，把整个学习计划移出当前计划。"
        "该操作不删除历史记录；调用时必须传 confirmed=true。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "plan_id": {"type": "integer", "description": "需要归档的学习计划 id"},
            "confirmed": {"type": "boolean", "description": "用户已明确确认移出计划时传 true"},
        },
        "required": ["plan_id", "confirmed"],
    },
}

_TOOL_UPDATE_STUDY_PLAN = {
    "name": "update_study_plan",
    "description": (
        "修改已存在学习计划的标题/描述/日期。用于学生看完计划想调整（如改标题、补说明、换日期）时。"
        "必须传 revision（计划当前版本号，查询计划时返回）；revision 不匹配说明计划已被改过，需重新查询。"
        "只改传入的非空字段；不能改任务项（任务项状态走 update_study_plan_item）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "plan_id": {"type": "integer", "description": "要修改的计划 id"},
            "title": {"type": "string", "description": "新标题，可选"},
            "description": {"type": "string", "description": "计划完整说明：AI 参考、学生要求、拆分理由，可选"},
            "planned_date": {"type": "string", "description": "计划日期 YYYY-MM-DD，可选"},
            "revision": {"type": "integer", "description": "计划当前 revision（乐观锁，查询时返回）"},
        },
        "required": ["plan_id", "revision"],
    },
}

_TOOL_COMPLETE_TASK_ITEM = {
    "name": "complete_task_item",
    "description": (
        "评估并完成一个学习计划项（U-044）。学生做完任务后调用："
        "基于对话历史判断学生是否掌握，写完成判定记录，达标置 done 进下一项，未达标置 needs_retry 留任务重做。"
        "判定依据：item.target（任务目标）+ 对话里学生作答。"
        "assessment=passed 学生掌握可进下一项；needs_retry 没掌握要重做；blocked 学生卡住需要帮助。"
        "注意：不要学生一说做完了就 passed，要先看对话是否充分判断掌握度；不足时先让学生发答案再评估。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "plan_item_id": {"type": "integer", "description": "计划项 id"},
            "assessment": {"type": "string", "enum": ["passed", "needs_retry", "blocked"]},
            "reason": {"type": "string", "description": "判定理由：学生哪里对了/哪里没掌握"},
            "evidence_summary": {"type": "string", "description": "证据摘录：对话里学生作答的关键内容或提交的答案"},
            "confidence": {"type": "number", "description": "置信度 0-1"},
        },
        "required": ["plan_item_id", "assessment", "reason"],
    },
}

_TOOL_GET_ATTRIBUTES = {
    "name": "get_attributes",
    "description": "获取学生学习档案当前值（各科能力/体育/投入度/掌握数）与历史成长曲线。",
    "input_schema": {
        "type": "object",
        "properties": {"student_id": {"type": "integer"}},
        "required": ["student_id"],
    },
}

_TOOL_SAVE_PROFILE_ONBOARDING = {
    "name": "save_profile_onboarding",
    "description": (
        "保存冷启动学习画像。"
        "当学生已经回答年级/学期/开学年级、学校/地区、薄弱科目、兴趣爱好、学习偏好或可学习时间时调用。"
        "这个工具用于补全基础画像，不需要大考成绩；不要用 record_interest 或 record_feedback 替代它。"
        "如果学生说“七年级下，开学八年级上”，grade 传“八年级”，semester 传“上册”，可在备注型字段不用额外保存七下。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "grade": {"type": "string", "description": "当前/即将学习年级，如 八年级"},
            "semester": {"type": "string", "description": "当前/即将学习学期或册次，如 上册"},
            "school": {"type": "string", "description": "学校，可选"},
            "district": {"type": "string", "description": "区县，可选"},
            "textbook_versions": {"type": "object", "description": "教材版本，如 {'英语':'译林版'}，可选"},
            "recent_scores": {"type": "object", "description": "近期成绩，0-100，可选"},
            "weak_subjects": {"type": "array", "items": {"type": "string"}, "description": "薄弱科目，如 ['英语']"},
            "study_preferences": {"type": "object", "description": "学习偏好，如 {'preferred_time':'下午','session_minutes':25}"},
            "interests": {"type": "array", "items": {"type": "string"}, "description": "学生自己说的兴趣，如 ['唱歌']"},
        },
        "required": ["student_id"],
    },
}

_TOOL_SAVE_NOTE = {
    "name": "save_note",
    "description": (
        "把弟弟学完的知识点整理成笔记并保存。你在讲完错题/看完视频/做完练习后，"
        "应主动问弟弟'要不要把这个知识点整理成笔记？'，弟弟确认后调用此工具。"
        "内容用 Markdown 结构化：含'我学到了什么''关键例子''易错点'等小节。"
        "不要让弟弟自己写 Markdown，你帮整理好让他确认。"
        "保存时自行判断 category 分类。"
        "讲错题时记的笔记，把错题id放进 source_ref，方便笔记详情页关联展示错题。"
        "弟弟说记笔记时，必须调用 save_note 工具把笔记落库（落库即为待确认草稿 status=draft，不进记忆），前端会把草稿渲染成卡片让弟弟确认；不要在对话里直接贴笔记正文。落库后对弟弟说『我整理了一版笔记，你看看对不对，可以就这样存或改一下』。弟弟在对话点「就这样存」确认后才转 confirmed 正式笔记；不要说已保存。错题复盘笔记调用前先和弟弟商量好内容再落草稿。"
        "保存错题复盘笔记时 category 使用'错题复盘'，source 使用'错题讲解'，source_ref 必须包含 error_book.id。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "title": {"type": "string", "description": "笔记标题，如'一般过去时'/'一元二次方程'"},
            "subject": {"type": "string", "description": "学科：语文/数学/英语/物理/化学/体育/其他"},
            "category": {
                "type": "string",
                "description": "学科下的细分分类，你根据内容判断：英语→词汇/语法/阅读/写作，数学→函数/几何/代数/统计，语文→古诗文/现代文/作文/基础知识，课外→兴趣/拓展。无合适细分填'未分类'，不要留空",
            },
            "content": {"type": "string", "description": "Markdown 正文，含小节标题和要点"},
            "knowledge_tags": {"type": "array", "items": {"type": "string"}, "description": "知识点标签，如['过去时','不规则动词']"},
            "source": {"type": "string", "description": "来源：错题讲解/视频学习/做题/素材整理/其他"},
            "source_ref": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "溯源id列表：错题讲解→错题id（error_book.id），视频学习→留空（BV号另存）。讲错题时必填关联错题id，其他来源留空",
            },
        },
        "required": ["student_id", "title", "content"],
    },
}

_TOOL_INIT_ATTRIBUTES = {
    "name": "init_attributes",
    "description": "初始化学生学习档案（录入最近大考各科成绩+体育成绩折算）。仅家长可用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "exam_scores": {
                "type": "object",
                "description": '各科大考成绩，如 {"chinese":85,"math":90,"english":78,"pe":80}',
                "properties": {
                    "chinese": {"type": "integer"},
                    "math": {"type": "integer"},
                    "english": {"type": "integer"},
                    "pe": {"type": "integer"},
                },
            },
        },
        "required": ["student_id", "exam_scores"],
    },
}

_TOOL_IMPORT_ERRORS_PROCESS = {
    "name": "import_errors_process",
    "description": (
        "处理已上传的错题导入批次：合成 PDF + 视觉解析每题作答。"
        "哥哥在前端输入框旁的相机按钮选好试卷照片上传后，会发来 batch_id，你调此工具解析。"
        "返回每题的题号/作答/分数（如有）。解析失败会返回 fallback_hint，你要据此引导哥哥在对话里口述题目，改走纯文本入本。"
        "如果用户本轮已经说有分数、给出第N题X分、给出标准答案，或说都没有分数和答案，说明已进入判分阶段，禁止再调用本工具，应调用 import_errors_grade。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "batch_id": {"type": "integer", "description": "错题导入批次 id（哥哥上传照片后发来的）"},
        },
        "required": ["batch_id"],
    },
}

_TOOL_IMPORT_ERRORS_GRADE = {
    "name": "import_errors_grade",
    "description": (
        "对已解析的错题导入批次判分并入错题本。仅家长可用。"
        "判分模式三选一：has_score（试卷上有老师批改的分数，传 manual_scores 题号→分数）/ "
        "no_score_has_answer（无分数有标准答案，传 standard_answers 题号→答案）/ "
        "no_score_no_answer（都没有，全部判错让用户复核，不传 manual_scores/standard_answers）。"
        "你要先和哥哥确认是哪种模式、收齐分数或答案后再调用。"
        "若最近上下文已有 batch_id，且用户本轮说「有分数」「第3题65分」等，应立即调用本工具，grade_mode=has_score，manual_scores 的题号必须用字符串。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "batch_id": {"type": "integer", "description": "错题导入批次 id"},
            "grade_mode": {
                "type": "string",
                "enum": ["has_score", "no_score_has_answer", "no_score_no_answer"],
                "description": "判分模式：has_score=有老师分数/no_score_has_answer=有标准答案/no_score_no_answer=都没有",
            },
            "manual_scores": {
                "type": "object",
                "description": '题号→分数，仅 has_score 模式传，如 {"1":85,"3":60}',
            },
            "standard_answers": {
                "type": "object",
                "description": '题号→标准答案，仅 no_score_has_answer 模式传，如 {"1":"went","2":"goes"}',
            },
        },
        "required": ["batch_id", "grade_mode"],
    },
}

_TOOL_RECOGNIZE_HOMEWORK_PHOTO_MARKDOWN = {
    "name": "recognize_homework_photo_markdown",
    "description": (
        "把已上传的拍题批改照片先识别成 Markdown，不做批改。"
        "用户通过聊天里的「拍题批改」上传作业/题目照片后，会发来 batch_id。"
        "你必须先调用本工具，保留题号、题干、选项、学生作答痕迹、作答置信度和不确定标记，让用户确认识别稿。"
        "如果学生作答低置信、看不清或带 [?]，不要批改，必须先追问学生确认。"
        "用户可以用自然语言修正第几题作答，修正后再进入批改。"
        "用户确认 Markdown 无误后，再调用 grade_homework_photo 并传 confirmed_markdown 批改。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "batch_id": {"type": "integer", "description": "拍题批改批次 id"},
        },
        "required": ["batch_id"],
    },
}

_TOOL_GRADE_HOMEWORK_PHOTO = {
    "name": "grade_homework_photo",
    "description": (
        "对已上传的拍题批改批次逐题批改。"
        "优先在用户确认 recognize_homework_photo_markdown 返回的 Markdown 识别稿后调用，并传 confirmed_markdown。"
        "逐题给出题目、学生作答、正确答案、是否正确、错因、知识点、简短讲解和置信度。"
        "如果用户修正过学生作答，批改前必须复述确认后的作答。"
        "student_answer 必须来自 confirmed_markdown 或用户明确修正，不要从原图重新猜。"
        "不确定正确答案或识别不清时 needs_review=true，并提醒用户确认；禁止直接把所有题自动入错题本。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "batch_id": {"type": "integer", "description": "拍题批改批次 id"},
            "confirmed_markdown": {"type": "string", "description": "用户确认过的 Markdown 识别稿"},
        },
        "required": ["batch_id"],
    },
}

_TOOL_SAVE_GRADED_HOMEWORK_ERRORS = {
    "name": "save_graded_homework_errors",
    "description": (
        "把用户确认需要保存的拍题批改错题写入错题本。"
        "只能保存用户明确确认的错题；不要把 grade_homework_photo 返回的所有题自动保存。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "batch_id": {"type": "integer", "description": "拍题批改批次 id"},
            "subject": {"type": "string", "description": "grade_homework_photo 返回的识别学科，如 物理/英语/数学"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "no": {"type": "string"},
                        "stem": {"type": "string"},
                        "student_answer": {"type": "string"},
                        "correct_answer": {"type": "string"},
                        "is_correct": {"type": "boolean"},
                        "error_point": {"type": "string"},
                        "knowledge_tags": {"type": "array", "items": {"type": "string"}},
                        "explanation": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "needs_review": {"type": "boolean"},
                    },
                    "required": ["no"],
                },
            },
        },
        "required": ["batch_id", "questions"],
    },
}

_TOOL_RECORD_INTEREST = {
    "name": "record_interest",
    "description": (
        "记录学生的兴趣/偏好（如喜欢唱歌、对物理感兴趣、爱看科普视频）。"
        "在对话中发现弟弟表达稳定兴趣时主动调用，方便以后个性化推荐。"
        "不要记一次性的临时话题，只记反复出现的稳定偏好。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "tag": {"type": "string", "description": "兴趣标签，如「唱歌」「物理科普」「篮球」"},
        },
        "required": ["student_id", "tag"],
    },
}

_TOOL_UPDATE_ATTRIBUTES = {
    "name": "update_attributes",
    "description": (
        "微调学生学习档案属性（如发现某科进步、投入度变化、掌握新知识点）。"
        "基于对话/做题反馈做小幅调整，不是大考初始化。调整会作为新快照追加（保留成长历史）。"
        "字段可选传，只传要改的。mastered_count 增量传（如 +1）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "delta": {
                "type": "object",
                "description": '属性增量调整，如 {"english":5,"mastered_count":1} 表示英语+5、掌握数+1。负数也可',
                "properties": {
                    "chinese": {"type": "integer"},
                    "math": {"type": "integer"},
                    "english": {"type": "integer"},
                    "pe": {"type": "integer"},
                    "engagement": {"type": "integer"},
                    "mastered_count": {"type": "integer"},
                },
            },
            "reason": {"type": "string", "description": "调整理由（如「英语错题减少，进步明显」）"},
        },
        "required": ["student_id", "delta"],
    },
}

_TOOL_UPDATE_PROFILE = {
    "name": "update_profile",
    "description": (
        "静默增量更新学生学习画像：对话中学生明确说出年级/学期/学校/区县/教材/薄弱科目/学习偏好/兴趣时调用，"
        "只传变化的字段，幂等。只记学生明确陈述的事实，推断（如从他问的内容猜年级）不要直接写，改成先用 present_profile_question 确认。"
        "textbook_versions 只保存用户明确说出的「科目 -> 版本/年级/册次」，例如 {'语文':'人教版八年级上册'}。"
        "教材任务缺版本时可在主答案末尾问一次；用户回答后立即增量更新。"
        "该字段只是身份画像，不是教材目录或课文内容证据，不能据此回答「第 X 课是什么」。"
        "兴趣用 add_interests/remove_interests 增删（自动去重）。不写学习反馈，不碰能力分与考试证据。"
        "不要用 save_profile_onboarding 做单字段增量；它是整批首存。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "grade": {"type": "string", "description": "如 八年级，只在学生明确说出时传"},
            "semester": {"type": "string", "description": "如 上册"},
            "school": {"type": "string"},
            "district": {"type": "string"},
            "textbook_versions": {"type": "object", "description": "教材版本，如 {'英语':'译林版'}"},
            "recent_scores": {"type": "object", "description": "近期成绩 0-100"},
            "weak_subjects": {"type": "array", "items": {"type": "string"}, "description": "自认薄弱科目，整体替换"},
            "study_preferences": {"type": "object", "description": "如 {'preferred_time':'下午','session_minutes':25}"},
            "add_interests": {"type": "array", "items": {"type": "string"}, "description": "新增兴趣标签"},
            "remove_interests": {"type": "array", "items": {"type": "string"}, "description": "移除兴趣标签"},
        },
        "required": ["student_id"],
    },
}

_TOOL_PRESENT_PROFILE_QUESTION = {
    "name": "present_profile_question",
    "description": (
        "[已停用] 不要调用本工具。按钮交互已停用，改用正文 1./2./3. 编号选项让学生回复数字或文字。原说明：向学生提一个画像问题并给出可点选项（手机端渲染成 chips，学生点一下即可，不必打字）。"
        "冷启动补全或确认推断时用：一次只问一个字段，可枚举字段（年级/学期/偏好时段/薄弱科目）给 3-5 个选项；"
        "开放字段（学校/区县）设 allow_other=true 让学生手填。"
        "推断不能直接写画像时（如从他问的内容猜年级），用它把推断变成一道确认题。"
        "调用后下一轮只输出问题文本、不要再调工具，等学生回答；学生点选项或回复数字/文本后，再用 update_profile 落库。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "field": {"type": "string", "description": "本次问的字段：grade/semester/school/district/weak_subjects/study_preferences/interest 等"},
            "question": {"type": "string", "description": "给学生的提问，语气温和，如「你现在几年级呀？」"},
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "选项展示文本，如「初二」"},
                        "value": {"type": "string", "description": "落库用的值，如「八年级」"},
                    },
                    "required": ["label", "value"],
                },
                "description": "可点选项列表；开放字段可给常见项 + allow_other",
            },
            "allow_other": {"type": "boolean", "description": "是否允许「其他」手填，开放字段（school/district）设 true"},
        },
        "required": ["student_id", "field", "question", "options"],
    },
}

_TOOL_PRESENT_CHOICE_QUESTION = {
    "name": "present_choice_question",
    "description": (
        "[已停用] 不要调用本工具。按钮交互已停用，改用正文 1./2./3. 编号选项让学生回复数字或文字。原说明：向学生提一个有限选项的选择题并给出可点按钮（手机端渲染成 chips，学生点一下即可，不必打字）。"
        "用于画像以外的任何需要学生在 2-4 个明确选项里做决定的场景：计划协商（先学数学还是英语）、"
        "任务执行（自己写还是看讲解）、试卷选择（在线做还是下载打印）等。"
        "一次只问一个选择，给 2-4 个互斥选项；设 allow_other=true 提供「都不符合，自己输入」兜底。"
        "question 和选项会由前端卡片显示；正文不要重复 question 文本或复述选项，只写一句简短引导并等待学生选择。"
        "画像冷启动字段（年级/学期/学校等）仍用 present_profile_question，不要用本工具替代。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "给学生的提问，语气温和、一次只问一个选择，如「今天先做数学还是英语？」"},
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "maxLength": 40, "description": "选项展示文本，如「先做数学」"},
                        "value": {"type": "string", "maxLength": 40, "description": "回传用的值，必须唯一，如「math」"},
                        "action": {"type": "string", "enum": ["return_to_main"], "description": "前端动作标记：return_to_main=切回主会话并预填，用于计划会话跑题引导学生回主会话建新计划"},
                        "prefill": {"type": "string", "maxLength": 100, "description": "action=return_to_main 时填入主会话输入框的预填文本，如学生原话「我想做英语阅读」"},
                    },
                    "required": ["label", "value"],
                },
                "description": "2-4 个可点选项，互斥且覆盖常见情况，value 必须唯一",
            },
            "allow_other": {"type": "boolean", "description": "是否提供「都不符合，自己输入」兜底，默认 true"},
        },
        "required": ["question", "options"],
    },
}

_TOOL_GRADE_LIGHT_ANSWER = {
    "name": "grade_light_answer",
    "description": (
        "对话轻练判分工具：学生在对话里随口练题（轻练）作答后，调本工具做确定性判分。"
        "用法：你在正文出一道题（用 present_response）→ 学生回复答案 → 你调本工具，"
        "传入题目（含标准答案和判分规则）和学生作答，返回 is_correct/score/detail。"
        "判分是纯计算、不落库、不计入任何统计（不进错题本/成绩/掌握度/画像）。"
        "选择题 answer 传选项字母（如 \"B\"）或索引（如 0），多选传数组（如 [0, 2]）；"
        "填空/计算题 answer 传文本，matcher 用 exact（精确，忽略大小写/空格/标点）"
        "或 levenshtein（拼写容错）或 float_tol（数值容差，match_params 传 eps）。"
        f"轻练最多 {settings.config.agent.light_practice.min_questions}-{settings.config.agent.light_practice.max_questions} 题，答完讲完即收尾，不建考试记录、不出试卷。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "question": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["single_choice", "multi_choice", "fill_blank", "math_answer"],
                    },
                    "stem": {"type": "string", "description": "题干"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "选择题选项，非选择题留空"},
                    "answer": {"description": "标准答案：选择题传字母/索引，多选传数组，填空/计算传文本"},
                    "score": {"type": "number", "description": "本题分值，>0"},
                    "grading": {
                        "type": "object",
                        "properties": {
                            "rule_type": {"type": "string", "enum": ["auto_exact", "auto_fuzzy", "manual"]},
                            "matcher": {"type": "string", "enum": ["exact", "levenshtein", "float_tol"]},
                            "match_params": {"type": "object"},
                        },
                        "required": ["rule_type", "matcher"],
                    },
                },
                "required": ["type", "stem", "answer", "score", "grading"],
            },
            "student_answer": {"type": "string", "description": "学生作答文本"},
        },
        "required": ["student_id", "question", "student_answer"],
    },
}


_TOOL_PRESENT_RESPONSE = {
    "name": "present_response",
    "description": (
        "最终回复工具：把你本轮要给用户看的完整回复组织成结构化内容块调用本工具，"
        "不要直接输出自由正文。每个段落/标题/列表/引用/公式/表格分别放入独立 block。\n"
        "正确示例：\n"
        "{\"blocks\": [\n"
        "  {\"type\": \"paragraph\", \"text\": \"先看定义。\"},\n"
        "  {\"type\": \"heading\", \"level\": 3, \"text\": \"第二块：抛物线与顶点\"},\n"
        "  {\"type\": \"list\", \"ordered\": false, \"items\": [\"a > 0：开口朝上\", \"a < 0：开口朝下\"]},\n"
        "  {\"type\": \"quote\", \"text\": \"顶点 = (-b/2a, f(-b/2a))\"}\n"
        "]}\n"
        "错误示例（不要把整段 markdown 塞进 text）：\n"
        "{\"blocks\": [{\"type\": \"paragraph\", \"text\": \"### 标题\\n- 列表项\"}]}\n"
        "约束：blocks 最多 40 项；文本非空；列表每项独立元素；表格列数一致；"
        "text 内禁止写 ###、---、行首 >、行首 - 等块级语法（用对应 block 类型表达）。"
        "禁止 emoji。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "blocks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 40,
                "description": "结构化内容块，每个元素需带 type 字段",
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["paragraph"]},
                                "text": {"type": "string", "description": "段落文本，可含行内 **粗体**/`code`/链接"},
                            },
                            "required": ["type", "text"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["heading"]},
                                "level": {"type": "integer", "enum": [2, 3, 4], "default": 3},
                                "text": {"type": "string", "description": "标题文本"},
                            },
                            "required": ["type", "text"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["list"]},
                                "ordered": {"type": "boolean", "default": False},
                                "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string"}},
                            },
                            "required": ["type", "items"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["quote"]},
                                "text": {"type": "string", "description": "引用/强调文本"},
                            },
                            "required": ["type", "text"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["code"]},
                                "language": {"type": "string", "description": "代码语言，可选"},
                                "code": {"type": "string"},
                            },
                            "required": ["type", "code"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["formula"]},
                                "latex": {"type": "string", "description": "LaTeX 公式"},
                                "display": {"type": "boolean", "default": False, "description": "True=独立行公式，False=行内公式"},
                            },
                            "required": ["type", "latex"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["table"]},
                                "headers": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "string"}},
                                "rows": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "array", "items": {"type": "string"}}},
                            },
                            "required": ["type", "headers", "rows"],
                        },
                    ],
                    "required": ["type"],
                },
            }
        },
        "required": ["blocks"],
    },
}


_TOOL_READ_MATERIAL = {
    "name": "read_material",
    "description": (
        "教材/课文问题的可信内容入口。回答前读取用户上传的具体素材。"
        "只引用 output.content 实际出现的信息，并在回答中带 material_id。"
        "content_source=confirmed_markdown 才是用户确认内容；auto_ready 是高置信机器识别，必须说明来源；"
        "needs_confirmation=true 时只能暂定并请用户核对。禁止补全图片中没出现的目录、作者或上下文。"
        "不要默认说「不能看图片」——你能看。"
        "非图片素材（pdf/doc）返回文件名和类型提示，引导用户描述。"
        "大素材（如整本教材）会返回目录并提示用 section 参数按章节读取；"
        "传 section 时只返回对应章节区间（如 section=\"Unit 3\"）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "material_id": {"type": "integer", "description": "素材 id（用户上传素材消息里带的）"},
            "section": {"type": "string", "description": "可选：按章节/单元读取（如 \"Unit 3\" 或 \"3\"），大素材必用，目录见 toc"},
        },
        "required": ["material_id"],
    },
}

_TOOL_LIST_MATERIALS = {
    "name": "list_materials",
    "description": (
        "列出当前账号有权限访问的学习素材。用户问「我有哪些素材」「我上传了什么资料」"
        "或需要根据已上传素材复习时，先调此工具获取素材 id、名称、类型、标签和确认状态。"
        "已确认 Markdown 可直接用于复习/讲解；未确认素材应引导用户先确认识别稿。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "可选来源过滤：student=学生上传，teacher=家长/平台上传（含教材，教材素材 source 是 teacher）。不确定或要全部时可省略"},
            "type": {"type": "string", "description": "可选素材类型过滤：image/pdf/doc 等（教材是 pdf 类型）"},
            "limit": {"type": "integer", "description": "最多返回多少条，默认 10，最大 20"},
        },
    },
}

_TOOL_QUERY_NOTES = {
    "name": "query_notes",
    "description": "查询学生记过的笔记列表（学习记录），了解弟弟之前学过什么、整理过什么。可选按学科过滤。",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "integer"},
            "subject": {"type": "string", "description": "可选学科过滤：语文/数学/英语/物理/化学/体育/其他"},
        },
        "required": ["student_id"],
    },
}

_TOOL_QUERY_FEEDBACK = {
    "name": "query_feedback",
    "description": "查询学生的学习反馈历史（看过什么视频/学了多久/自评/困难/错题原因），制定计划和同类练习时要参考错因反馈。",
    "input_schema": {
        "type": "object",
        "properties": {"student_id": {"type": "integer"}},
        "required": ["student_id"],
    },
}

_TOOL_QUERY_RECOMMENDATIONS = {
    "name": "query_recommendations",
    "description": "查询历史推荐过的资源（视频等）及弟弟是否点开过，避免重复推荐、了解弟弟对哪类资源感兴趣。",
    "input_schema": {
        "type": "object",
        "properties": {"student_id": {"type": "integer"}},
        "required": ["student_id"],
    },
}

ALL_TOOLS = [
    _TOOL_CREATE_EXAM,
    _TOOL_CREATE_PRACTICE_EXAM,
    _TOOL_QUERY_PRACTICE_EXAM_RESULT,
    _TOOL_QUERY_DIAGNOSIS,
    _TOOL_QUERY_LEARNING_MAP,
    _TOOL_QUERY_ERROR_BOOK,
    _TOOL_RECOMMEND_RESOURCE,
    _TOOL_BILIBILI_COURSE_ASSIST,
    _TOOL_SEARCH_PAPER_SOURCES,
    _TOOL_RECORD_FEEDBACK,
    _TOOL_CREATE_STUDY_PLAN,
    _TOOL_DRAFT_STUDY_PLAN,
    _TOOL_QUERY_STUDY_PLANS,
    _TOOL_ARCHIVE_STUDY_PLAN,
    _TOOL_UPDATE_STUDY_PLAN,
    _TOOL_COMPLETE_TASK_ITEM,
    _TOOL_GET_ATTRIBUTES,
    _TOOL_SAVE_PROFILE_ONBOARDING,
    _TOOL_INIT_ATTRIBUTES,
    _TOOL_SAVE_NOTE,
    _TOOL_IMPORT_ERRORS_PROCESS,
    _TOOL_IMPORT_ERRORS_GRADE,
    _TOOL_RECOGNIZE_HOMEWORK_PHOTO_MARKDOWN,
    _TOOL_GRADE_HOMEWORK_PHOTO,
    _TOOL_SAVE_GRADED_HOMEWORK_ERRORS,
    _TOOL_RECORD_INTEREST,
    _TOOL_UPDATE_ATTRIBUTES,
    _TOOL_UPDATE_PROFILE,
    _TOOL_PRESENT_PROFILE_QUESTION,
    _TOOL_PRESENT_CHOICE_QUESTION,
    _TOOL_READ_MATERIAL,
    _TOOL_LIST_MATERIALS,
    _TOOL_QUERY_NOTES,
    _TOOL_QUERY_FEEDBACK,
    _TOOL_QUERY_RECOMMENDATIONS,
    _TOOL_GRADE_LIGHT_ANSWER,
    _TOOL_PRESENT_RESPONSE,
    _TOOL_SEARCH_RESOURCE,
]
# TEACHER_TOOLS 不含仅学生会话使用的工具；其余与 ALL_TOOLS 一致
TEACHER_TOOLS = [
    t
    for t in ALL_TOOLS
    if t["name"] not in {"bilibili_course_assist", "query_practice_exam_result"}
]
CHANNEL_GUARDIAN_TOOLS = [
    _TOOL_QUERY_DIAGNOSIS,
    _TOOL_QUERY_LEARNING_MAP,
    _TOOL_QUERY_ERROR_BOOK,
    _TOOL_QUERY_STUDY_PLANS,
    _TOOL_GET_ATTRIBUTES,
    _TOOL_PRESENT_RESPONSE,
]
STUDENT_TOOLS = [
    _TOOL_QUERY_LEARNING_MAP,
    _TOOL_QUERY_ERROR_BOOK,
    _TOOL_RECOMMEND_RESOURCE,
    _TOOL_RECORD_FEEDBACK,
    _TOOL_DRAFT_STUDY_PLAN,
    _TOOL_QUERY_STUDY_PLANS,
    _TOOL_ARCHIVE_STUDY_PLAN,
    _TOOL_UPDATE_STUDY_PLAN,
    _TOOL_COMPLETE_TASK_ITEM,
    _TOOL_CREATE_PRACTICE_EXAM,
    _TOOL_QUERY_PRACTICE_EXAM_RESULT,
    _TOOL_GET_ATTRIBUTES,
    _TOOL_SAVE_PROFILE_ONBOARDING,
    _TOOL_SAVE_NOTE,
    _TOOL_IMPORT_ERRORS_PROCESS,
    _TOOL_IMPORT_ERRORS_GRADE,
    _TOOL_RECOGNIZE_HOMEWORK_PHOTO_MARKDOWN,
    _TOOL_GRADE_HOMEWORK_PHOTO,
    _TOOL_SAVE_GRADED_HOMEWORK_ERRORS,
    _TOOL_RECORD_INTEREST,
    _TOOL_UPDATE_ATTRIBUTES,
    _TOOL_UPDATE_PROFILE,
    _TOOL_PRESENT_PROFILE_QUESTION,
    _TOOL_PRESENT_CHOICE_QUESTION,
    _TOOL_READ_MATERIAL,
    _TOOL_LIST_MATERIALS,
    _TOOL_QUERY_NOTES,
    _TOOL_QUERY_FEEDBACK,
    _TOOL_QUERY_RECOMMENDATIONS,
    _TOOL_BILIBILI_COURSE_ASSIST,
    _TOOL_PRESENT_RESPONSE,
    _TOOL_GRADE_LIGHT_ANSWER,
]  # student: 查错题+请求推荐+记录反馈+看属性+记笔记+错题导入+记兴趣/调画像(不能出题/初始化)

# 兴趣模式工具集：学习工具全保留（用户可继续用计划/笔记/素材/记录等），叠加 B站资源搜索
HOBBY_TOOLS = STUDENT_TOOLS + [_TOOL_SEARCH_RESOURCE]


def tools_for_role(role: str) -> list[dict[str, Any]]:
    """按角色返回可用工具集（审查 C2：student 不给出题工具）。"""
    return TEACHER_TOOLS if role == "teacher" else STUDENT_TOOLS


def tools_for_actor(role: str, business_actor: str | None = None) -> list[dict[str, Any]]:
    if business_actor == "channel_guardian":
        return CHANNEL_GUARDIAN_TOOLS
    if business_actor == "hobby":
        return HOBBY_TOOLS
    return tools_for_role(role)

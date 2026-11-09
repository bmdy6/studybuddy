# 判分引擎常量（约束 #9）
DEFAULT_LEVENSHTEIN_TOLERANCE = 2
DEFAULT_FLOAT_EPS = 0.01
MANUAL_PASS_THRESHOLD = 0.6

# 诊断常量
DIAGNOSIS_TOP_N = 10
MASTERED_THRESHOLD = 0.85

# COS 韧性（约束 #18）
COS_UPLOAD_TIMEOUT_SEC = 30
COS_RETRY_MAX = 3
COS_RETRY_BACKOFF_BASE = 1.0
COS_CIRCUIT_FAIL_THRESHOLD = 5
COS_CIRCUIT_BREAK_SEC = 60

# 工具结果截断（移植 learn-claude-code s08 persist_large_output）
# 工具结果超阈值时只回灌预览给 LLM，防爆参数 400
TOOL_RESULT_PERSIST_THRESHOLD = 4000  # 超过此长度触发截断
TOOL_RESULT_PREVIEW_LEN = 2000  # 截断后回灌给 LLM 的预览长度

# 属性面板（P2.1 F5）
ATTRIBUTE_INIT_BASE = 60  # 初始化基准分
ATTRIBUTE_GAIN_PER_TAG = 3  # 单个 knowledge_tag 达标加分数

# 客户端
CLIENT_POLL_INTERVAL_SEC = 15

# 素材上传
ALLOWED_MATERIAL_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "pdf", "doc", "docx", "txt", "md"}
ALLOWED_EXAM_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

# 家庭目标与任务激励（证据第一阶段只收图片，视频待上传体积方案确定后再开）
ALLOWED_FAMILY_EVIDENCE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
FAMILY_EVIDENCE_MAX_COUNT = 9
FAMILY_PENDING_LIST_DEFAULT_LIMIT = 20
FAMILY_REWARD_RECORD_DEFAULT_LIMIT = 50

# 题型 → 中文标签（与前端 constants QUESTION_TYPE_LABELS 对齐）
QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multi_choice": "多选题",
    "fill_blank": "填空题",
    "transform": "句型转换",
    "translation": "翻译题",
    "essay": "作文",
    "math_answer": "解答题",
}
DEFAULT_QUESTION_TYPE_LABEL = "其他"

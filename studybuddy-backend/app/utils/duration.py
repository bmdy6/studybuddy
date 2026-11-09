from __future__ import annotations

import re

__all__ = ["parse_duration_minutes"]

# 学生反馈文案里学习时长的统一解析入口。
# 原先 growth/daily_record_service._minutes 和 growth/guardian_today._duration_minutes
# 逐字重复（4 行逻辑等价，仅注释/写法差异），抽到 utils 内聚，两处共用。
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(小时|分钟)")


def parse_duration_minutes(content: str) -> int:
    """从学生反馈文案解析学习时长（分钟）。

    排除 ``完成学习计划任务「…」`` 开头的自动反馈（含的是计划预计时长，非学生真实上报）。
    精确匹配该前缀，而非泛用"预计"二字，避免误丢学生真实上报（如"今天预计学了40分钟"）。
    支持"N小时""N分钟"混合，小时按 60 分钟换算，结果四舍五入。
    """
    if content.startswith("完成学习计划任务「"):
        return 0
    minutes = 0.0
    for value, unit in _DURATION_PATTERN.findall(content):
        minutes += float(value) * (60 if unit == "小时" else 1)
    return round(minutes)

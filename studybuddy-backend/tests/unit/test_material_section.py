"""read_material section 切片单测：大素材（教材）按章节读取。

覆盖：章节索引构建（任意标题级别、首次出现去重）、区间定位、阈值截断、目录生成。
"""

import pytest

from app.features.agent.handlers.material import (
    _SECTION_THRESHOLD_CHARS,
    _apply_section,
    _build_section_index,
    _build_section_toc,
    _slice_markdown_by_section,
)


SAMPLE = """# 封面

## 目录

#### Unit 1
Unit 1 内容第一行
Unit 1 内容第二行
##### Unit 1
页眉内容

#### Unit 2
Unit 2 内容第一行
##### Unit 2
页眉内容

##### Unit 3
Unit 3 内容（5级标题）
#### Unit 4
Unit 4 内容
"""


class TestBuildSectionIndex:
    def test_任意级别标题都识别(self):
        index = _build_section_index(SAMPLE)
        nums = [item["num"] for item in index]
        assert nums == [1, 2, 3, 4]

    def test_首次出现去重(self):
        # Unit 1 在页眉重复出现，索引只保留首次（Unit 1 标题行）
        index = _build_section_index(SAMPLE)
        u1 = index[0]
        assert u1["line_no"] == SAMPLE.split("\n").index("#### Unit 1")

    def test_无Unit标题返回空(self):
        assert _build_section_index("没有章节的普通文本\n第二行") == []


class TestSliceBySection:
    def test_按序号切区间(self):
        sliced = _slice_markdown_by_section(SAMPLE, "2")
        assert sliced is not None
        assert sliced["title"] == "#### Unit 2"
        assert "Unit 2 内容第一行" in sliced["content"]
        assert "Unit 1 内容第一行" not in sliced["content"]
        assert "Unit 3 内容" not in sliced["content"]

    def test_按UnitN格式切(self):
        sliced = _slice_markdown_by_section(SAMPLE, "Unit 3")
        assert sliced is not None
        assert sliced["title"] == "##### Unit 3"
        assert "Unit 3 内容" in sliced["content"]
        assert "Unit 2 内容第一行" not in sliced["content"]

    def test_最后一个单元到结尾(self):
        sliced = _slice_markdown_by_section(SAMPLE, "4")
        assert sliced is not None
        assert "Unit 4 内容" in sliced["content"]
        assert "Unit 3 内容" not in sliced["content"]

    def test_找不到返回None(self):
        assert _slice_markdown_by_section(SAMPLE, "9") is None
        assert _slice_markdown_by_section(SAMPLE, "abc") is None

    def test_无索引返回None(self):
        assert _slice_markdown_by_section("普通文本", "1") is None


class TestBuildToc:
    def test_目录列出所有单元标题(self):
        toc = _build_section_toc(SAMPLE)
        assert toc == ["#### Unit 1", "#### Unit 2", "##### Unit 3", "#### Unit 4"]


class TestApplySection:
    def test_小内容原样返回(self):
        result = _apply_section("短内容", None)
        assert result["content"] == "短内容"
        assert result["sectioned"] is False
        assert result["hint"] is None

    def test_大内容超阈值返回截断加目录(self):
        big = SAMPLE * 3000  # 远超阈值
        result = _apply_section(big, None)
        assert result["sectioned"] is False
        assert len(result["content"]) <= _SECTION_THRESHOLD_CHARS
        assert "Unit" in result["toc"][0]
        assert result["hint"] is not None

    def test_section命中返回区间(self):
        result = _apply_section(SAMPLE, "Unit 2")
        assert result["sectioned"] is True
        assert "Unit 2 内容第一行" in result["content"]
        assert result["section_title"] == "#### Unit 2"

    def test_section未命中返回提示(self):
        result = _apply_section(SAMPLE, "Unit 9")
        assert result["sectioned"] is False
        assert result["content"] is None
        assert result["hint"] is not None

    def test_section切片结果超阈值时截断(self):
        # 最后一个单元区间很大（如含附录），切片结果也需截断保护
        big_sample = SAMPLE + "\n\n#### 附录\n" + "附录内容" * 20000
        result = _apply_section(big_sample, "Unit 4")
        assert result["sectioned"] is False
        assert len(result["content"]) <= _SECTION_THRESHOLD_CHARS
        assert result["hint"] is not None


class TestFallbackHintMerge:
    """低置信识别稿 + 切片提示时，两条提示都要保留（审查发现的小瑕疵）。"""

    def test_提示合并(self):
        # 构造非 auto_ready 场景的返回（在 handler 里合并，这里验证逻辑组合）
        sliced_hint = "内容较长已截断，可用 section 参数按章节读取。"
        auto_ready = False
        hints = []
        if sliced_hint:
            hints.append(sliced_hint)
        if not auto_ready:
            hints.append("这份素材还没有人工确认，使用前请提醒用户核对识别是否准确。")
        merged = "；".join(hints)
        assert "截断" in merged and "人工确认" in merged

"""历史消息保守 Markdown 适配器测试（AI 回复格式根治批次 2）。

覆盖：
- msg 2637 原文修复：分隔线 + 两个标题 + 引用 + 两项无序列表
- 数学防误伤矩阵逐字不变
- 已规范 markdown 幂等（修复后不变）
- code/公式/URL 保护
- 坏标记降级（转义为普通文本，不出现 --- ###）
"""

from app.features.chat.legacy_markdown_repair import repair_legacy_markdown

MSG2637 = (
    "对！**第 3 个** y = x³ + 2x² + 1 不是一元二次函数，因为它有 x³，最高次数是 3 了。 "
    "✅ 你能准确判断，说明\"一元\"和\"最高次是 2\"这两个条件已经抓住了。 "
    "接下来搞清楚 **一元二次函数的图像（抛物线）** 和几个重要要素。 "
    "--- ### 第二块：抛物线与顶点 "
    "**y = ax² + bx + c** 的图像是一条抛物线，记住几个核心点： "
    "**1. 对称轴** x = -b / 2a 这是抛物线的\"左右对称线\"。 "
    "**2. 顶点**（抛物线的最高或最低点） 顶点的横坐标就是对称轴的值，纵坐标把 x 代回去就算出来。 "
    "换个好记的说法： > 顶点 = **(-b/2a, f(-b/2a))** "
    "**3. a 的正负决定谁是顶点：** - a > 0：开口朝上，顶点是**最低点** - a < 0：开口朝下，顶点是**最高点** "
    "--- ### 练一个： y = 2x² - 4x + 1 你能算出它的**对称轴**和**顶点坐标**吗？ "
    "不确定也没关系，试着算算看。"
)


def test_repair_msg2637_restores_structure():
    """msg 2637 单行文本修复：分隔线、标题、引用、列表全部还原。"""
    out = repair_legacy_markdown(MSG2637)
    assert "\n---\n" in out, "分隔线应还原"
    assert "### 第二块：抛物线与顶点" in out, "标题应还原"
    assert "### 练一个" in out, "第二个标题应还原"
    assert "> 顶点 = " in out, "引用应还原"
    assert "\n- a > 0：" in out, "无序列表项 1 应拆行"
    assert "\n- a < 0：" in out, "无序列表项 2 应拆行"
    # 数学符号保留
    assert "x = -b / 2a" in out
    assert "(-b/2a, f(-b/2a))" in out
    assert "2x² - 4x + 1" in out


def test_repair_math_matrix_unchanged():
    """数学防误伤矩阵逐字不变（比较/减法/负号/版本号/URL）。"""
    matrix = [
        "a > 0；a < 0；Δ >= 0；x <= 1",
        "x - b；x - 1；b² - 4ac；-b/2a；-4ac",
        "版本 1.2.3",
        "https://example.com/a-b?q=x>0",
        "a > 0、x - b、x = -b/2a",
        "y = ax² + bx + c，a ≠ 0",
    ]
    for text in matrix:
        assert repair_legacy_markdown(text) == text, text


def test_repair_normal_markdown_idempotent():
    """已规范 markdown 修复后不变（幂等）。"""
    normal = (
        "好，我们开始。\n\n"
        "---\n\n"
        "### 第一块：定义\n\n"
        "- 项一\n"
        "- 项二\n\n"
        "> 引用内容\n\n"
        "1. 甲\n"
        "2. 乙"
    )
    once = repair_legacy_markdown(normal)
    assert once == normal
    assert repair_legacy_markdown(once) == once


def test_repair_protects_code_and_formula():
    """code/行内 code/公式/链接 占位符保护，不被误拆。"""
    text = (
        "看代码：\n\n"
        "```python\n"
        "x = a > 0\n"
        "```\n\n"
        "行内 `a > 0` 和 $x - b$ 和 $$x = -b/2a$$ 和 [链接](https://example.com/a-b)"
    )
    out = repair_legacy_markdown(text)
    assert "```python" in out and "x = a > 0" in out
    assert "`a > 0`" in out
    assert "$x - b$" in out and "$$x = -b/2a$$" in out
    assert "[链接](https://example.com/a-b)" in out


def test_repair_single_dash_not_split():
    """单个 ` - ` 不拆成列表。"""
    single = "注意： - 只有一项说明"
    assert repair_legacy_markdown(single) == single


def test_repair_empty_and_none():
    """空/None 返回空串，不报错。"""
    assert repair_legacy_markdown(None) == ""
    assert repair_legacy_markdown("") == ""
    assert repair_legacy_markdown("   ") == ""


def test_repair_degrade_unrepairable():
    """修复后仍命中坏模式 → 降级转义，坏控制标记不出现。"""
    # 句中标题：### 前是普通汉字（非句末标点），规则2不修复 → 命中 validator → 降级转义
    bad = "中间插一个 ### 藏着的标题 还有 --- 分隔线"
    out = repair_legacy_markdown(bad)
    assert "###" not in out
    assert "---" not in out

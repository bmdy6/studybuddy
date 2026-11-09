import asyncio
import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.features.exams.answer_review_parser import extract_answer_review_items
from app.features.materials.markdown_extraction_service import (
    encode_image_for_vision,
    extract_llm_message_text,
    normalize_markdown_extraction_result,
    recognize_images_to_markdown,
)


def test_normalize_markdown_extraction_result_keeps_markdown_and_uncertain_points():
    raw = """
    ```markdown
    ### 知识点3 误差和错误

    学生作答：偏大 / 误差 / 不能

    **识别置信度**：85%
    **需要人工确认的内容**：第三空是否为“不能”
    **适合作为哪类学习素材**：初中物理易错点
    ```
    """

    result = normalize_markdown_extraction_result(raw)

    assert "误差和错误" in result.markdown
    assert "学生作答：偏大 / 误差 / 不能" in result.markdown
    assert result.confidence == "medium"
    assert result.uncertain_points == ["第三空是否为“不能”"]
    assert result.content_type == "初中物理易错点"
    assert result.raw_text == raw


def test_normalize_markdown_extraction_result_adds_answer_review_section_for_homework_like_content():
    raw = """
    ### 学以致用 1

    (1) 刻度尺的分度值为 [?] cm。

    学生作答：[?]

    **识别置信度**：中
    **适合作为哪类学习素材**：初中物理测量练习
    """

    result = normalize_markdown_extraction_result(raw)

    assert "## 学生作答核对" in result.markdown
    assert "第1题：学生作答需要确认" in result.markdown
    assert "第1题：学生作答需要确认" in result.uncertain_points


def test_normalize_marks_low_confidence_student_answer_as_uncertain():
    raw = """
    1. 选择正确读数。
    学生作答：B
    作答置信度：低
    需确认：圈选痕迹太淡

    **识别置信度**：中
    **适合作为哪类学习素材**：初中物理测量练习
    """

    result = normalize_markdown_extraction_result(raw)

    assert "第1题：学生作答需要确认" in result.markdown
    assert "第1题：学生作答需要确认" in result.uncertain_points


def test_normalize_keeps_clear_medium_confidence_answer_as_identified():
    raw = """
    1. 选择正确读数。
    学生作答：B
    作答置信度：中
    需确认：无

    **识别置信度**：中
    **适合作为哪类学习素材**：初中物理测量练习
    """

    result = normalize_markdown_extraction_result(raw)

    assert "第1题：学生作答已识别为 B" in result.markdown
    assert "第1题：学生作答需要确认" not in result.uncertain_points


def test_extract_answer_review_items_parses_confidence_and_reason():
    markdown = """
    1. 选择正确读数
    学生作答：B
    作答置信度：低
    需确认：圈选痕迹太淡

    2. 填空题
    学生作答：误差
    作答置信度：高
    需确认：无
    """

    items = extract_answer_review_items(markdown)

    assert [item.question_no for item in items] == ["1", "2"]
    assert items[0].detected_answer == "B"
    assert items[0].confidence == "low"
    assert items[0].needs_review is True
    assert items[0].review_reason == "圈选痕迹太淡"
    assert items[0].answer_type == "choice"
    assert items[1].detected_answer == "误差"
    assert items[1].confidence == "high"
    assert items[1].needs_review is False
    assert items[1].answer_type == "text"


def test_extract_answer_review_items_marks_unclear_answer_as_review_needed():
    markdown = """
    第3题
    学生作答：[?]
    作答置信度：中
    需确认：无
    """

    items = extract_answer_review_items(markdown)

    assert len(items) == 1
    assert items[0].question_no == "3"
    assert items[0].needs_review is True
    assert items[0].review_reason == "学生作答看不清"


def test_extract_answer_review_items_parses_question_no_and_answer_on_same_line():
    markdown = """
    学以致用 1

    （1）题干：刻度尺读数。学生作答：4.60cm，2.55cm 作答置信度：高
    （2）题干：秒表读数。学生作答：1 min 29.5s 作答置信度：中 需确认：秒数略模糊
    """

    items = extract_answer_review_items(markdown)

    assert [item.question_no for item in items] == ["1", "2"]
    assert items[0].detected_answer == "4.60cm，2.55cm"
    assert items[0].confidence == "high"
    assert items[1].detected_answer == "1 min 29.5s"
    assert items[1].needs_review is True
    assert items[1].review_reason == "秒数略模糊"


def test_extract_answer_review_items_parses_bullet_answer_block_from_real_photo_markdown():
    markdown = """
    (1) 如图甲所示，刻度尺的分度值为 [1?] cm，所测物体的长度是 [?] cm。
    *   学生作答：`4.60`；`2.55`
    *   作答置信度：高
    *   需确认：学生答案清晰。

    (2) 如图乙所示，秒表显示的时间是 [?] min [?] s。
    *   学生作答：`1`；`25.5`
    *   作答置信度：中高
    *   需确认：秒数略模糊。
    """

    items = extract_answer_review_items(markdown)

    assert [item.question_no for item in items] == ["1", "2"]
    assert items[0].detected_answer == "4.60；2.55"
    assert items[0].confidence == "high"
    assert items[0].needs_review is False
    assert items[1].detected_answer == "1；25.5"
    assert items[1].confidence == "medium"
    assert items[1].needs_review is True
    assert items[1].review_reason == "秒数略模糊。"


def test_extract_answer_review_items_parses_markdown_table_from_real_photo_markdown():
    markdown = """
    ### 【学以致用1】
    | 题号 | 题干 | 学生作答 | 作答置信度 | 需确认 |
    | ---- | ---- | -------- | ---------- | ------ |
    | (1) | 如图甲所示，刻度尺的分度值为1mm。 | 4.60 | 高 | 无 |
    | (2) | 如图乙所示，秒表显示的时间是______min ______s。 | 3min25.7s | 高 | 无 |

    ### 【学以致用2】
    | 题号 | 题干 | 学生作答 | 作答置信度 | 需确认 |
    | ---- | ---- | -------- | ---------- | ------ |
    | 【学以致用2】 | 木尺受潮后测量值比较。 | 偏小；误差；不能 | 高 | 无 |
    """

    items = extract_answer_review_items(markdown)

    assert [item.question_no for item in items] == ["1", "2", "学以致用2"]
    assert items[0].detected_answer == "4.60"
    assert items[0].needs_review is False
    assert items[1].detected_answer == "3min25.7s"
    assert items[2].detected_answer == "偏小；误差；不能"
    assert items[2].confidence == "high"


def test_extract_answer_review_items_ignores_reasoning_outline_and_knowledge_headings():
    markdown = """
    首先看结构：
    1. 知识点1：机械秒表的结构
    2. 知识点2：学以致用1，题目（1）和（2）
    3. 知识点3：误差和错误

    # 2.测量时间——机械秒表（如图所示）
    ## 知识点2：学以致用1
    ### （1）刻度尺测量
    题干：如图甲所示，刻度尺的分度值为____。
    学生作答：[?]（图中学生作答看不清具体数值，需确认）
    作答置信度：低
    需确认：刻度尺的分度值和物体长度

    ### （2）秒表读数
    题干：秒表显示的时间是____ min ____ s。
    学生作答：3min39.5s
    作答置信度：高
    需确认：无

    ### 知识点3：误差和错误
    3. 误差与错误区别：误差只能减小，不能避免；错误可以避免
    学以致用2：
    题干：木尺受潮后测量值比较。
    学生作答：[?]（图中学生作答看不清，需确认）
    作答置信度：低
    需确认：学生的填空内容
    """

    items = extract_answer_review_items(markdown)

    assert [item.question_no for item in items] == ["1", "2", "学以致用2"]
    assert items[0].detected_answer == "[?]（图中学生作答看不清具体数值，需确认）"
    assert items[1].detected_answer == "3min39.5s"
    assert items[2].detected_answer == "[?]（图中学生作答看不清，需确认）"


def test_recognize_images_to_markdown_returns_external_ocr_result_without_calling_mimo(tmp_path):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"fake-image")
    external_result = SimpleNamespace(
        markdown="### 题目\n\n**识别置信度**：高",
        provider="external-ocr",
        elapsed_ms=123,
        warnings=["ocr-warning"],
    )

    with (
        patch("app.features.materials.markdown_extraction_service.markdown_ocr_service.recognize_photos_to_markdown", return_value=external_result) as mock_ocr,
        patch("app.features.materials.markdown_extraction_service.ai_service.call_llm", new_callable=AsyncMock) as mock_llm,
    ):
        result = asyncio.run(recognize_images_to_markdown([str(image_path)], mode="homework_photo"))

    mock_ocr.assert_called_once_with([str(image_path)])
    mock_llm.assert_not_called()
    assert result.provider == "external-ocr"
    assert result.elapsed_ms == 123
    assert result.warnings == ["ocr-warning"]
    assert result.confidence == "high"


def test_recognize_images_to_markdown_falls_back_to_mimo_message_content_when_external_ocr_missing(tmp_path):
    image_path = tmp_path / "photo.png"
    Image.new("RGB", (120, 80), color="white").save(image_path)
    llm_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="### 回退识别\n\n**识别置信度**：中\n**需要人工确认的内容**：无\n**适合作为哪类学习素材**：课堂练习"
                )
            )
        ]
    )

    with (
        patch("app.features.materials.markdown_extraction_service.markdown_ocr_service.recognize_photos_to_markdown", return_value=None) as mock_ocr,
        patch("app.features.materials.markdown_extraction_service.ai_service.call_llm", new_callable=AsyncMock, return_value=llm_response) as mock_llm,
        patch("app.features.materials.markdown_extraction_service.extract_llm_message_text", wraps=extract_llm_message_text) as mock_extract,
    ):
        result = asyncio.run(recognize_images_to_markdown([str(image_path)], mode="homework_photo"))

    mock_ocr.assert_called_once_with([str(image_path)])
    mock_llm.assert_awaited_once()
    mock_extract.assert_called_once_with(llm_response.choices[0].message)
    assert result.provider == "mimo"
    assert result.confidence == "medium"
    assert "回退识别" in result.markdown


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (SimpleNamespace(reasoning_content="来自 reasoning"), "来自 reasoning"),
        (SimpleNamespace(model_extra={"reasoning_content": "来自 extra"}), "来自 extra"),
    ],
)
def test_extract_llm_message_text_supports_reasoning_content_sources(message, expected):
    assert extract_llm_message_text(message) == expected


def test_encode_image_for_vision_compresses_large_image_to_jpeg_with_max_side_1800(tmp_path):
    image_path = tmp_path / "large.png"
    Image.new("RGB", (4200, 3100), color="white").save(image_path, format="PNG")

    payload = encode_image_for_vision(str(image_path))

    data_url = payload["image_url"]["url"]
    assert data_url.startswith("data:image/jpeg;base64,")
    encoded = data_url.split(",", 1)[1]
    decoded = base64.b64decode(encoded)
    with Image.open(BytesIO(decoded)) as img:
        assert img.format == "JPEG"
        assert max(img.size) <= 1800


def test_recognize_images_to_markdown_raises_clear_error_for_empty_images():
    with pytest.raises(ValueError, match="image_paths must not be empty"):
        asyncio.run(recognize_images_to_markdown([], mode="homework_photo"))

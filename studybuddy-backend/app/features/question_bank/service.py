"""题库对外门面：re-export 各子模块公开函数。

调用方写 ``from app.features.question_bank import service as question_bank_service``，
保持 ``question_bank_service.xxx`` 调用面不变（架构文档 §6：迁移期门面降低破坏面）。
实现拆在 ``search_service`` / ``source_service`` / ``upload_service`` / ``item_service``，
技术债中6 落实：先增内聚（拆子模块）再搬目录（约束 #6）。
"""

from __future__ import annotations

from .parsers import (
    _DuckDuckGoParser,
    _OfficialLinkParser,
    _clean_text,
    _extract_bing_url,
    _extract_duckduckgo_url,
    _extract_visible_text,
    _estimate_question_count,
    _grade_for_yidianedu,
    _looks_like_pdf,
    _parse_bing_results,
    _parse_yidianedu_results,
    _strip_tags,
    _type_id_for_yidianedu,
)
from .scoring import (
    _adapter_from_query,
    _classify_candidate,
    _dedupe_candidates,
    _dedupe_queries,
    _hash_question,
    _hash_url,
    _is_relevant_candidate,
    _looks_like_official_edu_source,
    _score_candidate,
)
from .search_service import (
    _candidate_from_official_link,
    _looks_like_paper_link,
    _same_or_child_domain,
    _school_query_aliases,
    _search_yidianedu,
    build_official_source_queries,
    build_official_source_site_seeds,
    build_paper_search_queries,
    discover_official_source_links,
    save_paper_candidates,
    search_public_paper_candidates,
)

from .source_service import (
    create_manual_paper_source,
    list_paper_sources,
    update_paper_source_status,
    _suggested_status_from_review,
    get_review_metrics,
    _auto_approval_decision,
    fetch_paper_source_preview,
    _preview_response_from_text,
    _looks_like_login_or_blocked,
    get_paper_source_full_preview,
    review_paper_source_content,
    review_paper_source,
)

from .upload_service import (
    _extract_pdf_text,
    _extract_uploaded_paper_text,
    validate_uploaded_paper_file,
    create_uploaded_paper_source,
    _render_pdf_pages_to_png,
    _extract_scanned_pdf_text_with_vision,
)

from .item_service import (
    _infer_question_type,
    _extract_options,
    _trim_question_noise,
    _parse_questions_from_text,
    _enrich_existing_question_bank_item,
    _to_bank_item,
    list_question_bank_items,
    update_question_bank_item_status,
    _parsed_item_status,
    parse_paper_source_to_items,
    search_and_save_paper_sources,
    to_item,
)

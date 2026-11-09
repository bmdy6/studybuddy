from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.models.p2 import RecommendationBoundary, ResourceRecommendation
from .schemas import RecommendationBoundaryItem, RecommendationItem

DEFAULT_RECOMMENDATION_PLATFORMS = ["bilibili"]
DEFAULT_RECOMMENDATION_DAILY_LIMIT = 3


def save_recommendation(
    db: Session,
    student_id: int,
    title: str,
    url: str,
    reason: str | None = None,
    platform: str = "bilibili",
    related_interests: list | None = None,
    related_tags: list | None = None,
) -> RecommendationItem:
    rec = ResourceRecommendation(
        student_id=student_id,
        title=title,
        platform=platform,
        url=url,
        reason=reason,
        related_interests=related_interests,
        related_tags=related_tags,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return RecommendationItem(id=rec.id, title=rec.title, platform=rec.platform, url=rec.url, reason=rec.reason, clicked=rec.clicked)


def list_recommendations(db: Session, student_id: int) -> list[RecommendationItem]:
    items = (
        db.query(ResourceRecommendation)
        .filter(ResourceRecommendation.student_id == student_id)
        .order_by(ResourceRecommendation.id.desc())
        .limit(50)
        .all()
    )
    return [RecommendationItem(id=r.id, title=r.title, platform=r.platform, url=r.url, reason=r.reason, clicked=r.clicked) for r in items]


def mark_clicked(db: Session, rec_id: int, student_ids: list[int] | None = None) -> bool:
    query = db.query(ResourceRecommendation).filter(ResourceRecommendation.id == rec_id)
    if student_ids is not None:
        if not student_ids:
            return False
        query = query.filter(ResourceRecommendation.student_id.in_(student_ids))
    rec = query.first()
    if not rec:
        return False
    rec.clicked = True
    db.commit()
    return True


def _clean_string_list(values: list[str] | None, limit: int = 20) -> list[str]:
    clean: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if item and item not in clean:
            clean.append(item[:64])
        if len(clean) >= limit:
            break
    return clean


def _to_boundary(student_id: int, boundary: RecommendationBoundary | None = None) -> RecommendationBoundaryItem:
    if not boundary:
        return RecommendationBoundaryItem(
            student_id=student_id,
            allowed_platforms=DEFAULT_RECOMMENDATION_PLATFORMS,
            blocked_keywords=[],
            daily_limit=DEFAULT_RECOMMENDATION_DAILY_LIMIT,
            allow_entertainment_interests=False,
        )
    return RecommendationBoundaryItem(
        student_id=boundary.student_id,
        allowed_platforms=[str(item) for item in boundary.allowed_platforms or []],
        blocked_keywords=[str(item) for item in boundary.blocked_keywords or []],
        daily_limit=boundary.daily_limit,
        allow_entertainment_interests=boundary.allow_entertainment_interests,
    )


def get_recommendation_boundary(db: Session, student_id: int) -> RecommendationBoundaryItem:
    boundary = db.query(RecommendationBoundary).filter(RecommendationBoundary.student_id == student_id).first()
    return _to_boundary(student_id, boundary)


def update_recommendation_boundary(
    db: Session,
    student_id: int,
    allowed_platforms: list[str],
    blocked_keywords: list[str],
    daily_limit: int,
    allow_entertainment_interests: bool,
    updated_by: int | None = None,
) -> RecommendationBoundaryItem:
    platforms = _clean_string_list(allowed_platforms) or DEFAULT_RECOMMENDATION_PLATFORMS
    keywords = _clean_string_list(blocked_keywords, limit=50)
    safe_limit = max(0, min(20, int(daily_limit)))
    boundary = db.query(RecommendationBoundary).filter(RecommendationBoundary.student_id == student_id).first()
    if not boundary:
        boundary = RecommendationBoundary(student_id=student_id, allowed_platforms=platforms, blocked_keywords=keywords)
        db.add(boundary)
    boundary.allowed_platforms = platforms
    boundary.blocked_keywords = keywords
    boundary.daily_limit = safe_limit
    boundary.allow_entertainment_interests = allow_entertainment_interests
    boundary.updated_by = updated_by
    db.commit()
    db.refresh(boundary)
    return _to_boundary(student_id, boundary)


def check_recommendation_allowed(db: Session, student_id: int, platform: str, keyword: str) -> str | None:
    boundary = get_recommendation_boundary(db, student_id)
    if platform not in boundary.allowed_platforms:
        return f"家长推荐边界暂未允许平台：{platform}"
    clean_keyword = keyword.strip().lower()
    for blocked in boundary.blocked_keywords:
        if blocked.strip() and blocked.strip().lower() in clean_keyword:
            return f"家长推荐边界已屏蔽关键词：{blocked}"
    today_start = datetime.combine(date.today(), time.min)
    today_count = (
        db.query(ResourceRecommendation)
        .filter(ResourceRecommendation.student_id == student_id, ResourceRecommendation.created_at >= today_start)
        .count()
    )
    if today_count >= boundary.daily_limit:
        return f"今天推荐资源已达到家长设置的上限：{boundary.daily_limit} 个"
    return None

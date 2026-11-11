#!/usr/bin/env python3
"""从国家中小学智慧教育平台导入教材 PDF 到知了素材库（教材资产 P0）。

用法（在 studybuddy-backend 目录下执行）：
  PYTHONPATH=. ../scripts/import_textbook.py \\
    --content-id c69fbfe9-1233-33a6-d354-45ec9a34d1c9 \\
    --name "译林英语七年级上册（2024新版）" \\
    --subject 英语 --edition 译林版 --grade 七年级 \\
    --student-username <示例学生用户名>

流程：
  1. 从官方资源详情取得 PDF 并下载（渠道可能变化，见 ~/Documents/40-学习笔记/66-调研/xcc/[P0] 教材获取-国家智慧教育平台渠道.md）
  2. 校验 API 声明的 MD5，同时计算 SHA-256 供人工核对
  3. 确保系统账号 textbook_system 存在（role=teacher、不可登录），并绑定目标学生
  4. 复用 upload_material_async 上传（type=pdf, student_id=示例学生）
  5. ensure_extraction 触发 pdf-inspector 解析

版权：只走官方渠道、个人自用，不公开分发。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import secrets
import sys

import requests
import urllib3

# 官方 CDN 证书链在部分环境不完整，跳过校验的告警只影响控制台输出
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/studybuddy-backend")

# 官方资源详情 API 与下载直链域名（2026-08 实测可用，官方可能调整，需开学季重验）
DETAIL_API = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{content_id}.json"
AUTH_HEADERS = {
    "Authorization": "Bearer 0",
    "Origin": "https://basic.smartedu.cn",
    "Referer": "https://basic.smartedu.cn/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-ND-AUTH": 'MAC id="0",nonce="0",mac="0"',
}

SYSTEM_ACCOUNT_USERNAME = "textbook_system"
SYSTEM_ACCOUNT_DISPLAY = "知了教材"


class _NoVerifySession(requests.Session):
    """本地/容器环境证书链常不完整，官方平台为公网 HTTPS，跳过证书校验仅用于下载。"""

    def request(self, *args, **kwargs):
        kwargs.setdefault("verify", False)
        return super().request(*args, **kwargs)


_session = _NoVerifySession()


def fetch_detail(content_id: str) -> dict:
    """调官方资源详情 API，返回 JSON。"""
    url = DETAIL_API.format(content_id=content_id)
    resp = _session.get(url, headers=AUTH_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def pick_pdf_item(data: dict) -> dict | None:
    """从 ti_items 里挑 PDF 资源（ti_format=pdf）。"""
    for item in data.get("ti_items", []):
        if item.get("ti_format") == "pdf":
            return item
    return None


def download_pdf(item: dict) -> bytes:
    """下载 PDF 文件字节。"""
    storages = item.get("ti_storages") or []
    if not storages:
        raise RuntimeError("资源没有可下载的 PDF 直链")
    resp = _session.get(storages[0], headers=AUTH_HEADERS, timeout=120)
    resp.raise_for_status()
    return resp.content


def verify_sha256(data: bytes, expected_md5: str | None) -> str:
    """校验文件完整性：API 声明的是 MD5（ti_md5），同时计算 SHA-256 供资产记录。"""
    if expected_md5:
        actual_md5 = hashlib.md5(data).hexdigest()
        if actual_md5 != expected_md5:
            raise RuntimeError(f"MD5 不匹配：实际 {actual_md5}，期望 {expected_md5}")
    return hashlib.sha256(data).hexdigest()


def ensure_system_account(db, username: str, display_name: str) -> object:
    """确保系统账号存在（role=teacher、不可登录），返回 User。"""
    from app.models.user import User
    from app.utils.security import hash_password

    user = db.query(User).filter(User.username == username).first()
    if user:
        return user
    user = User(
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(24)),
        role="teacher",
        display_name=display_name,
        web_login_enabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"已创建系统账号 {username}（不可登录）")
    return user


def ensure_student_binding(db, teacher_id: int, student_id: int) -> None:
    """确保系统账号与目标学生绑定（教材归属学生所需的家长校验）。"""
    from app.core.auth import access_service

    if not access_service.teacher_can_access_student(db, teacher_id, student_id):
        access_service.bind_teacher_student(db, teacher_id, student_id)
        db.commit()
        print(f"已绑定系统账号 -> 学生 {student_id}")


def main() -> int:
    import asyncio

    return asyncio.run(_main())


async def _main() -> int:
    parser = argparse.ArgumentParser(description="从国家智慧教育平台导入教材 PDF")
    parser.add_argument("--content-id", required=True, help="教材资源 contentId（官方平台教材 URL 中获取）")
    parser.add_argument("--name", required=True, help="素材名称（如 译林英语七年级上册）")
    parser.add_argument("--isbn", default="", help="兼容旧命令，当前不参与校验")
    parser.add_argument("--subject", default="", help="学科标签（如 英语）")
    parser.add_argument("--edition", default="", help="版本标签（如 译林版）")
    parser.add_argument("--grade", default="", help="年级标签（如 七年级）")
    parser.add_argument("--student-username", required=True, help="教材归属的学生用户名")
    args = parser.parse_args()

    from app.database import SessionLocal
    from app.features.materials.extraction_service import ensure_extraction
    from app.features.materials.service import upload_material_async
    from app.models.user import User

    # 1. 拉取资源详情 + 下载 PDF
    print(f"拉取资源详情：{args.content_id}")
    detail = fetch_detail(args.content_id)
    title = detail.get("title") or (detail.get("global_title") or {}).get("zh-CN") or args.name
    pdf_item = pick_pdf_item(detail)
    if not pdf_item:
        print(f"错误：资源里没有 PDF（ti_items={len(detail.get('ti_items', []))}）", file=sys.stderr)
        return 2
    print(f"标题：{title}，PDF 大小：{pdf_item.get('ti_size')} 字节")
    data = download_pdf(pdf_item)
    sha256 = verify_sha256(data, pdf_item.get("ti_md5"))
    print(f"下载完成：{len(data)} 字节，SHA-256={sha256}")

    # 2. 落库
    db = SessionLocal()
    try:
        student = db.query(User).filter(User.username == args.student_username).first()
        if not student:
            print(f"错误：学生账号 {args.student_username} 不存在", file=sys.stderr)
            return 2

        system_user = ensure_system_account(db, SYSTEM_ACCOUNT_USERNAME, SYSTEM_ACCOUNT_DISPLAY)
        ensure_student_binding(db, system_user.id, student.id)

        tags = [t for t in ("教材", args.subject, args.edition, args.grade) if t]
        name = args.name or title
        ext = "pdf"
        resp = await upload_material_async(
            db,
            io.BytesIO(data).getvalue(),
            ext,
            name,
            "pdf",
            tags,
            system_user,
            target_student_id=student.id,
        )
        if resp.is_duplicate:
            print(f"素材已存在（id={resp.material_id}），检查识别状态…")
            from app.models.material import Material

            existing = db.get(Material, resp.material_id)
            # 识别未完成（processing/failed/无内容）时强制重识别
            if not existing.recognized_markdown:
                extraction = await ensure_extraction(db, resp.material_id, system_user, force=True)
                print(
                    f"重识别完成：id={resp.material_id} status={extraction.recognition_status} "
                    f"provider={extraction.recognition_provider}"
                )
                return 0
            print("识别已完成，跳过")
            return 0

        # 3. 触发识别（pdf-inspector 解析）
        extraction = await ensure_extraction(db, resp.material_id, system_user, force=False)
        print(
            f"入库完成：material_id={resp.material_id} name={resp.name} "
            f"status={extraction.recognition_status} provider={extraction.recognition_provider}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

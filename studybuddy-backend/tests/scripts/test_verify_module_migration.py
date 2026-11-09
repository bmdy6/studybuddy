"""verify_module_migration.py 的 TDD 测试。

用 subprocess 调脚本（黑盒 CLI 测试），断言三个子命令在「漏迁」场景 exit 1 且
stderr 含具体差异描述；在「完全一致」场景 exit 0。

不 import 脚本本身：CLI 的入口/退出码/输出流必须端到端验证才真实。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 测试文件: tests/scripts/test_verify_module_migration.py
# parents[0]=scripts tests[1]=tests parents[2]=studybuddy-backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_DIR / "scripts" / "verify_module_migration.py"
VENV_PYTHON = Path(sys.executable)  # 用当前解释器，CI/本地都兼容（不硬编码 .venv 路径，CI 无 .venv/bin/python）
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "migration"

# 旧 import 路径正则：迁移前 `from app.services.question_bank import xxx`，
# 迁移后应改为 `from app.modules.question_bank import xxx`。
OLD_IMPORT_PATTERN = r"from app\.services\.question_bank import"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """以子进程调脚本，capture stdout/stderr，不抛异常（自己判 exit code）。"""
    return subprocess.run(
        [str(VENV_PYTHON), str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------- openapi-diff ----------------


def test_openapi_diff_missing_path_exits_1():
    """漏迁场景：after 少了 /api/question-bank/papers，必须 exit 1 并打印缺失路径。"""
    result = _run(
        "openapi-diff",
        "--before", str(FIXTURE_DIR / "before_openapi.json"),
        "--after", str(FIXTURE_DIR / "after_openapi.json"),
    )
    assert result.returncode == 1, f"期望 exit 1，实际 {result.returncode}；stderr={result.stderr}"
    assert "/api/question-bank/papers" in result.stderr
    # schema 也应被检出（PaperOut 在 after 中缺失）
    assert "PaperOut" in result.stderr


def test_openapi_diff_identical_exits_0():
    """一致场景：before==after（同一份文件），exit 0。"""
    same = FIXTURE_DIR / "before_openapi.json"
    result = _run("openapi-diff", "--before", str(same), "--after", str(same))
    assert result.returncode == 0, f"期望 exit 0，实际 {result.returncode}；stderr={result.stderr}"


def test_openapi_diff_missing_method_exits_1():
    """method 盲区：path 还在但 POST 漏迁，必须 exit 1 并报 operation 缺失。"""
    result = _run(
        "openapi-diff",
        "--before", str(FIXTURE_DIR / "before_method_openapi.json"),
        "--after", str(FIXTURE_DIR / "after_method_openapi.json"),
    )
    assert result.returncode == 1, f"期望 exit 1，实际 {result.returncode}；stderr={result.stderr}"
    assert "POST /api/exam-batches" in result.stderr
    # path 没丢、GET 还在，不应误报 GET 缺失
    assert "GET /api/exam-batches" not in result.stderr


# ---------------- old-path ----------------


def test_old_path_residual_import_exits_1():
    """漏迁场景：源码里残留旧 import，必须 exit 1 并打印命中行。"""
    result = _run(
        "old-path",
        "--pattern", OLD_IMPORT_PATTERN,
        "--root", str(FIXTURE_DIR / "src_with_old_import"),
    )
    assert result.returncode == 1, f"期望 exit 1，实际 {result.returncode}；stderr={result.stderr}"
    assert "from app.services.question_bank import" in result.stderr


def test_old_path_clean_exits_0():
    """一致场景：源码已迁移到新路径，无旧 import 残留，exit 0。"""
    result = _run(
        "old-path",
        "--pattern", OLD_IMPORT_PATTERN,
        "--root", str(FIXTURE_DIR / "src_clean"),
    )
    assert result.returncode == 0, f"期望 exit 0，实际 {result.returncode}；stderr={result.stderr}"


# ---------------- fn-diff ----------------


def test_fn_diff_missing_fn_exits_1():
    """漏迁场景：after 目录缺 search_public_paper_candidates，必须 exit 1 并打印缺失函数名。"""
    result = _run(
        "fn-diff",
        "--before-fns", str(FIXTURE_DIR / "before_fns.txt"),
        "--after-fns", str(FIXTURE_DIR / "after_fns_missing"),
    )
    assert result.returncode == 1, f"期望 exit 1，实际 {result.returncode}；stderr={result.stderr}"
    assert "search_public_paper_candidates" in result.stderr


def test_fn_diff_complete_exits_0():
    """一致场景：after 目录函数齐全，exit 0。"""
    result = _run(
        "fn-diff",
        "--before-fns", str(FIXTURE_DIR / "before_fns.txt"),
        "--after-fns", str(FIXTURE_DIR / "after_fns_complete"),
    )
    assert result.returncode == 0, f"期望 exit 0，实际 {result.returncode}；stderr={result.stderr}"


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))

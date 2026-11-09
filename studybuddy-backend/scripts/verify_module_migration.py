"""模块化迁移防丢校验脚本（sdd plan Task 1）。

用途：在把 app/services/*_service.py 拆成模块化包之前/之后，校验对外契约没丢东西。
三个子命令：
  - openapi-diff：对比两份 openapi.json 的 path:method 对和 components.schemas
  - old-path：用 rg 检查目录下是否还有旧 import 路径残留
  - fn-diff：对比 before 函数清单与 after 目录的函数名集合

退出码语义（故意只有两态）：
  0 = 一致（迁移没丢东西，安全）
  1 = 发现差异（疑似漏迁，需人工核对）

为何用 1 而不是枚举式多态码：脚本主要在 CI/Makefile 里 `&&` 串接或被 shell `if` 当
布尔条件用，两态语义最清晰；rg/file 读取等工具层失败也归入 1（fail-safe：无法证明
安全就当不安全，阻塞流水线让人介入），避免引入第三种「工具坏了」码让 CI 逻辑变复杂。

为何不依赖 DB/运行中的服务：openapi.json 由调用方（CI 里 FastAPI 导出）传入，
脚本本身只读 json/文件 + 调 rg，保证能在任意环境（含无 MySQL 的 CI runner）跑。

用法示例：
  .venv/bin/python scripts/verify_module_migration.py openapi-diff \\
      --before before.json --after after.json
  .venv/bin/python scripts/verify_module_migration.py old-path \\
      --pattern 'from app\\.services\\.question_bank import' --root app/
  .venv/bin/python scripts/verify_module_migration.py fn-diff \\
      --before-fns before_fns.txt --after-fns app/modules/question_bank/
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# path 展成 `METHOD /path` 对再比：只比 path 键会漏掉「path 还在但某 method 漏挂」
# （迁移最常出的错）。components.schemas 比 schema 名键集合。其他键（servers/info/
# security）多为环境相关，不反映业务漏迁，刻意不比。
_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}
)


def _iter_operations(paths: dict) -> set[str]:
    """把 openapi paths 展成 `METHOD /path` 对集合。

    只取 HTTP method 键，跳过 path 级的 parameters/summary 等非 method 键，
    避免 path-level 参数被误当 method。
    """
    ops: set[str] = set()
    for path, methods in paths.items():
        for method in methods:
            if method.upper() in _HTTP_METHODS:
                ops.add(f"{method.upper()} {path}")
    return ops


def _diff_openapi(before_path: Path, after_path: Path) -> tuple[list[str], bool]:
    """对比两份 openapi.json 的 path:method 对 + components.schemas 键集合。

    采用「键集合」对比而非深 diff：本脚本是防丢校验，目标是「有没有少路由/少模型」，
    而不是「路由内部 schema 是否变化」（后者属回归测试范畴，交给单测/类型检查兜底）。
    path 对比到 method 粒度：path 还在但某 method 漏注册（如漏挂 @router.delete）
    也算「少路由」--这是只比 path 键会漏的盲区。
    返回 (差异描述列表, 是否一致)。
    """
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))

    before_ops = _iter_operations(before.get("paths", {}))
    after_ops = _iter_operations(after.get("paths", {}))
    before_schemas = set(before.get("components", {}).get("schemas", {}).keys())
    after_schemas = set(after.get("components", {}).get("schemas", {}).keys())

    diffs: list[str] = []
    for op in sorted(before_ops - after_ops):
        diffs.append(f"operation 缺失: {op}")
    for op in sorted(after_ops - before_ops):
        diffs.append(f"operation 新增: {op}")
    for schema in sorted(before_schemas - after_schemas):
        diffs.append(f"schema 缺失: {schema}")
    for schema in sorted(after_schemas - before_schemas):
        diffs.append(f"schema 新增: {schema}")

    return diffs, len(diffs) == 0


def _run_rg(args: list[str]) -> tuple[int, str, str | None]:
    """调 rg，返回 (returncode, stdout, stderr_or_None)。

    rg 退出码语义：0=找到匹配，1=无匹配，2=出错（pattern 非法/路径不存在等）。
    """
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        # rg 未安装：无法证明无残留，fail-safe 返回「工具不可用」状态。
        return -1, "", "rg 未安装，无法执行校验（请安装 ripgrep）"
    return result.returncode, result.stdout, result.stderr if result.stderr else None


def _check_old_path(pattern: str, root: Path) -> tuple[list[str], bool]:
    """用 rg 检查 root 下是否还有匹配 pattern 的旧 import 残留。

    用 rg 而不是 Python re：rg 对大仓库快几个数量级，自动尊重 .gitignore，
    与开发同学日常 grep 体验一致，命中行带文件名+行号便于复核。
    返回 (命中行列表, 是否无残留)。
    """
    # -n 带行号，--no-heading 保证非 TTY 下也是 file:line:content 格式，便于解析/阅读。
    code, out, err = _run_rg(["rg", "-n", "--no-heading", pattern, str(root)])
    if code == -1:
        return [err or ""], False  # type: ignore[list-item]
    if code == 0:
        # 找到匹配 = 残留 = 漏迁
        hits = [line for line in out.rstrip("\n").splitlines() if line]
        return hits, False
    if code == 1:
        # 无匹配 = 干净
        return [], True
    # code == 2 或其他：rg 出错，fail-safe
    return [f"rg 执行失败 (exit={code}): {err or ''}"], False


def _diff_fns(before_fns_path: Path, after_dir: Path) -> tuple[list[str], bool]:
    """对比 before_fns.txt 与 after_dir 下所有 .py 的函数名集合。

    只判「缺失」（before 有、after 没有）= 漏迁；after 多出来的函数是新增，不算漏迁，
    不触发 exit 1。这跟 openapi-diff 的对称 diff 不同：openapi 是对外契约必须完全一致，
    fn 清单是「必须保留的对外 API 名单」，新增实现细节允许。
    返回 (差异描述列表, 是否齐全)。
    """
    before_fns = {
        line.strip()
        for line in before_fns_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    # 严格按 spec 用 `^def |^async def `：只抓模块级函数，不抓类方法。
    code, out, err = _run_rg(
        ["rg", "-N", "--no-heading", r"^def |^async def ", str(after_dir), "-t", "py"]
    )
    if code == -1:
        return [err or ""], False  # type: ignore[list-item]
    if code not in (0, 1):
        return [f"rg 执行失败 (exit={code}): {err or ''}"], False

    # 从命中行里抠函数名：兼容 `def foo(` 和 `async def foo(`，
    # 也容忍 rg 的 file:line:content 前缀（regex 用 \b 定位 def 关键字即可）。
    fn_name_re = re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    after_fns: set[str] = set()
    for line in out.splitlines():
        m = fn_name_re.search(line)
        if m:
            after_fns.add(m.group(1))

    missing = sorted(before_fns - after_fns)
    if missing:
        return ["缺失函数:", *[f"  - {name}" for name in missing]], False
    return [], True


def _emit(section: str, lines: list[str]) -> None:
    """把差异描述打到 stderr（不是 stdout）：差异是诊断信息，不是数据流。

    任务约定 stderr 含具体差异描述，且 CI 里 stdout 留给正餐数据，stderr 走诊断。
    """
    print(section, file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)


def cmd_openapi_diff(args: argparse.Namespace) -> int:
    diffs, ok = _diff_openapi(Path(args.before), Path(args.after))
    if not ok:
        _emit("openapi 差异：", [f"  - {d}" for d in diffs])
        return 1
    return 0


def cmd_old_path(args: argparse.Namespace) -> int:
    hits, ok = _check_old_path(args.pattern, Path(args.root))
    if not ok:
        _emit("旧 import 路径残留：", [f"  {h}" for h in hits])
        return 1
    return 0


def cmd_fn_diff(args: argparse.Namespace) -> int:
    diffs, ok = _diff_fns(Path(args.before_fns), Path(args.after_fns))
    if not ok:
        _emit("函数清单差异：", diffs)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="模块化迁移防丢校验（openapi-diff / old-path / fn-diff）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_oa = sub.add_parser(
        "openapi-diff", help="对比两份 openapi.json 的 paths 和 components.schemas"
    )
    p_oa.add_argument("--before", required=True, help="迁移前 openapi.json 路径")
    p_oa.add_argument("--after", required=True, help="迁移后 openapi.json 路径")
    p_oa.set_defaults(func=cmd_openapi_diff)

    p_op = sub.add_parser("old-path", help="用 rg 检查旧 import 路径残留")
    p_op.add_argument("--pattern", required=True, help="旧 import 路径正则")
    p_op.add_argument("--root", required=True, help="要扫描的目录")
    p_op.set_defaults(func=cmd_old_path)

    p_fd = sub.add_parser(
        "fn-diff", help="对比 before 函数清单与 after 目录的函数名集合"
    )
    p_fd.add_argument(
        "--before-fns", required=True, help="before 函数清单文件（每行一个函数名）"
    )
    p_fd.add_argument(
        "--after-fns", required=True, help="after 目录（递归提取所有 .py 中的 def）"
    )
    p_fd.set_defaults(func=cmd_fn_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

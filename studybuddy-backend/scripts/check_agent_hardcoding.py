#!/usr/bin/env python3
"""Agent 配置与提示词硬编码检查（批次3）。

扫描指定生产文件，检查三类可机验规则：
  1. 已迁移的提示词常量不得再承载字符串字面量（只允许 load()/render() 别名）
  2. 已迁移的配置词表不得以整组元组字面量回到 agent 代码；工具 schema 不得手写
     subject code enum；轻练边界文案不得裸写
  3. 提示词模板调用契约：.md 无单花括号变量、agent 代码无 .format() 处理提示词

输出相对路径+行号+规则名+修复建议（GitHub annotation 格式，本地同样可读）。
任何发现退出码 1，零发现退出码 0。

用法：
    python3 scripts/check_agent_hardcoding.py            # 常规扫描
    python3 scripts/check_agent_hardcoding.py --self-test  # 自测：临时违规夹具必须被检出

纯标准库（ast/pathlib/re/sys/tempfile），不引入依赖。
"""

from __future__ import annotations

import ast
import re
import sys
import tempfile
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 配置：扫描范围与规则数据（与批次1/2迁移清单一一对应，改动需同步此处）
# ─────────────────────────────────────────────────────────────────────────────

# 相对 backend 根的扫描文件（收敛范围，避免误报）
SCAN_FILES = [
    "app/features/agent/context.py",
    "app/features/agent/agent_loop.py",
    "app/features/agent/plan_draft_guard.py",
    "app/features/agent/textbook_honesty_guard.py",
    "app/features/agent/tools.py",
    "app/config.py",
    "config.yaml",
]
# 提示词 .md 按目录扫描
PROMPT_GLOB = "app/prompts/agent/*.md"

# 规则 1：已迁移提示词常量名（不再允许承载字符串字面量）
MIGRATED_PROMPT_CONSTANTS = frozenset({
    "_PRACTICE_EXAM_ROUTE_HINT",
    "PRACTICE_EXAM_ROUTE_RETRY_PROMPT",
    "PRESENT_RESPONSE_FAILURE_TEXT",
    "PRESENT_RESPONSE_CORRECTION_PROMPT",
    "PLAN_GUARD_FAILURE_TEXT",
    "PLAN_GUARD_CORRECTION_PROMPT",
    "PLAINTEXT_DRAFT_PLACEHOLDER",
    "TEXTBOOK_GUARD_CORRECTION_PROMPT",
    "TEXTBOOK_HONESTY_FIXED_REPLY_TPL",
})

# 规则 2a：已迁移配置词表常量名（不允许再以整组元组字面量赋值回代码）
MIGRATED_KEYWORD_CONSTANTS = frozenset({
    "_LIGHT_PRACTICE_TRIGGER_WORDS",
    "_LIGHT_PRACTICE_EXIT_WORDS",
    "_UNCERTAINTY_HINTS",
    "_QUESTION_HINTS",
    "_OCR_ATTRIBUTION_HINTS",
    "_UNCONFIRMED_SAFETY_HINTS",
    "TEXTBOOK_SENSITIVE_KEYWORDS",
    "PLAN_NEGOTIATION_KEYWORDS",
    "_GOAL_QUESTION_HINTS",
})

# 规则 2b：subject code 配置集合（与 config.yaml agent.practice_exam.subject_codes 对应）
SUBJECT_CODES = frozenset({"math", "english", "chinese"})

# 规则 2c：轻练边界裸文案（已参数化，出现即视为漏迁移）
LIGHT_BOUNDARY_TEXTS = ("1-3", "答完 3 题", "2-3 道")

# 规则 3：单花括号变量（排除双花括号 {{var}}）
SINGLE_BRACE_VAR = re.compile(r"(?<!\{)\{[a-zA-Z_][a-zA-Z0-9_]*\}(?!\})")


class Finding:
    """一条检查发现。"""

    __slots__ = ("file", "line", "rule", "message")

    def __init__(self, file: str, line: int, rule: str, message: str):
        self.file = file
        self.line = line
        self.rule = rule
        self.message = message

    def to_annotation(self) -> str:
        return f"::error file={self.file},line={self.line}::{self.rule} {self.message}"

    def to_readable(self) -> str:
        return f"{self.file}:{self.line} [{self.rule}] {self.message}"


def find_backend_root(start: Path) -> Path | None:
    """从任意位置向上定位 studybuddy-backend 根（含 config.yaml 的目录）。"""
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    while True:
        if (cur / "config.yaml").is_file() and (cur / "app").is_dir():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def _is_string_literal_value(node: ast.expr) -> bool:
    """字符串字面量：单常量或 + 拼接的常量串。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_string_literal_value(node.left) and _is_string_literal_value(node.right)
    return False


def _is_tuple_literal(node: ast.expr) -> bool:
    """整组元组字面量（元素都是字符串常量），即词表数据形态。"""
    return isinstance(node, (ast.Tuple, ast.List)) and all(
        isinstance(el, ast.Constant) and isinstance(el.value, str) for el in node.elts
    ) and bool(node.elts)


def _assign_target_names(node: ast.Assign) -> list[str]:
    return [t.id for t in node.targets if isinstance(t, ast.Name)]


def _check_rule1(tree: ast.AST, file: str) -> list[Finding]:
    """规则 1：旧提示词常量不承载字符串字面量。"""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for name in _assign_target_names(node):
            if name not in MIGRATED_PROMPT_CONSTANTS:
                continue
            if _is_string_literal_value(node.value):
                findings.append(Finding(
                    file, node.lineno, "rule1-prompt-literal",
                    f"已迁移提示词常量 {name} 仍以字符串字面量赋值，请改用 "
                    f"load(\"agent/...\") / render() 读取 app/prompts/agent/*.md。",
                ))
    return findings


def _check_rule2a(tree: ast.AST, file: str) -> list[Finding]:
    """规则 2a：配置词表不再以整组元组字面量回到代码。"""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for name in _assign_target_names(node):
            if name not in MIGRATED_KEYWORD_CONSTANTS:
                continue
            if _is_tuple_literal(node.value):
                findings.append(Finding(
                    file, node.lineno, "rule2-keyword-literal",
                    f"配置词表常量 {name} 仍以元组字面量硬编码，请从 "
                    f"settings.config.agent.* 读取。",
                ))
    return findings


def _check_rule2b(tree: ast.AST, file: str) -> list[Finding]:
    """规则 2b：工具 schema 不得手写两个以上 subject code enum。"""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "enum"):
                continue
            if not isinstance(value, (ast.List, ast.Tuple)):
                continue
            codes = {
                el.value for el in value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
            overlap = codes & SUBJECT_CODES
            if len(overlap) >= 2:
                findings.append(Finding(
                    file, node.lineno, "rule2-subject-enum",
                    "工具 schema 手写 subject code enum（"
                    + "/".join(sorted(overlap)) + "），请改用 "
                    "_SUBJECT_CODES（settings.config.agent.practice_exam.subject_codes）。",
                ))
    return findings


def _check_rule2c(text: str, file: str) -> list[Finding]:
    """规则 2c：轻练边界裸文案（提示词/代码均已参数化）。"""
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for phrase in LIGHT_BOUNDARY_TEXTS:
            if phrase in line:
                findings.append(Finding(
                    file, lineno, "rule2-light-boundary",
                    f"轻练边界文案「{phrase}」裸写在文件中，请用 "
                    "{{light_practice_min_questions}}/{{light_practice_max_questions}} "
                    "参数化（配置在 config.yaml agent.light_practice）。",
                ))
    return findings


def _check_rule3_python(tree: ast.AST, file: str) -> list[Finding]:
    """规则 3a：agent 代码不得用 .format() 处理提示词。"""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            findings.append(Finding(
                file, node.lineno, "rule3-format-call",
                "发现 .format() 调用，提示词模板应使用 {{var}} 占位符 + "
                "app.prompts.render()，禁止 .format()。",
            ))
    return findings


def _check_rule3_md(text: str, file: str) -> list[Finding]:
    """规则 3b：.md 模板无单花括号变量（{{var}} 合法）。"""
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in SINGLE_BRACE_VAR.finditer(line):
            findings.append(Finding(
                file, lineno, "rule3-single-brace",
                f"单花括号变量「{match.group(0)}」出现在提示词模板，"
                "请使用双花括号 {{var}}（app.prompts.render 替换）。",
            ))
    return findings


def scan_backend(backend_root: Path) -> list[Finding]:
    """扫描全部目标文件，返回排序后的发现列表。"""
    findings: list[Finding] = []
    for rel in SCAN_FILES:
        path = backend_root / rel
        if not path.is_file():
            findings.append(Finding(rel, 0, "scan-missing", "扫描目标文件不存在"))
            continue
        if rel.endswith(".py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                findings.append(Finding(rel, exc.lineno or 0, "scan-syntax", f"语法解析失败：{exc}"))
                continue
            findings.extend(_check_rule1(tree, rel))
            findings.extend(_check_rule2a(tree, rel))
            findings.extend(_check_rule2b(tree, rel))
            findings.extend(_check_rule3_python(tree, rel))
            findings.extend(_check_rule2c(path.read_text(encoding="utf-8"), rel))
        elif rel.endswith((".yaml", ".yml")):
            findings.extend(_check_rule2c(path.read_text(encoding="utf-8"), rel))
    for md in sorted((backend_root / "app/prompts/agent").glob("*.md")):
        rel = str(md.relative_to(backend_root))
        text = md.read_text(encoding="utf-8")
        findings.extend(_check_rule3_md(text, rel))
        findings.extend(_check_rule2c(text, rel))
    findings.sort(key=lambda f: (f.file, f.line))
    return findings


def run_self_test(backend_root: Path) -> None:
    """--self-test：临时违规夹具必须被检出（退出码 1 + 文件/行号 + annotation），清理后退出 0。"""
    fixture_violations = {
        "rule1": "PRACTICE_EXAM_ROUTE_RETRY_PROMPT = \"违规字符串\"\n",
        "rule2a": "_LIGHT_PRACTICE_TRIGGER_WORDS = (\"练几道\", \"考我一道\")\n",
        "rule2b": "subject_enum = {\"enum\": [\"math\", \"english\"]}\n",
        "rule3a": "text = \"你好 {}\".format(\"x\")\n",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for rule, content in fixture_violations.items():
            fake = tmp_path / f"fake_{rule}.py"
            fake.write_text(content, encoding="utf-8")
            tree = ast.parse(content, filename=str(fake))
            # 直接对 AST 跑对应规则（不依赖 backend 路径定位）
            results: list[Finding] = []
            results.extend(_check_rule1(tree, str(fake)))
            results.extend(_check_rule2a(tree, str(fake)))
            results.extend(_check_rule2b(tree, str(fake)))
            results.extend(_check_rule3_python(tree, str(fake)))
            if not results:
                raise SystemExit(f"self-test 失败：{rule} 夹具未被检出")
            # 校验 annotation 格式与行号
            ann = results[0].to_annotation()
            if not ann.startswith("::error file=") or "line=" not in ann:
                raise SystemExit(f"self-test 失败：{rule} annotation 格式错误：{ann}")
            if results[0].line < 1:
                raise SystemExit(f"self-test 失败：{rule} 行号缺失")
    # 真实扫描路径自检：backend 定位 + 正常扫描应 0 发现（验收前若已有发现会在此暴露）
    real = scan_backend(backend_root)
    if real:
        for f in real:
            print(f.to_readable(), file=sys.stderr)
        raise SystemExit(
            f"self-test 失败：真实代码已有 {len(real)} 处硬编码发现，请先修复再提交"
        )
    print(f"self-test 通过：4 个违规夹具全部检出，真实扫描 0 发现（backend={backend_root}）")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    script_path = Path(__file__).resolve()
    backend_root = find_backend_root(script_path)
    if backend_root is None:
        print("错误：无法定位 studybuddy-backend 根目录（未找到含 config.yaml + app/ 的目录）", file=sys.stderr)
        return 2

    if "--self-test" in argv:
        run_self_test(backend_root)
        return 0

    findings = scan_backend(backend_root)
    for f in findings:
        print(f.to_annotation())
        print(f.to_readable())
    if findings:
        print(f"\n发现 {len(findings)} 处硬编码问题，请修复后重试。", file=sys.stderr)
        return 1
    print("检查通过：0 findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

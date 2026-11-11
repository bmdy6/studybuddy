#!/usr/bin/env python3
"""知了开发日志素材采集 v2：从 git 提交结构化提取"今天/近 N 天做了什么"。

用法: python3 scripts/devlog/collect_devlog.py [天数]   # 默认 1 天
产出: stdout 输出 markdown 素材清单，按类型分组，供写开发日志参考。
"""
import datetime
import os
import re
import subprocess
import sys

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 1
repo = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
os.chdir(repo)
since = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()
today = datetime.date.today()

raw = subprocess.run(
    ["git", "log", "--oneline", "--since", since, "--pretty=%h|%s"],
    capture_output=True, text=True,
).stdout

groups = {
    "🆕 新功能 / 产品进展": [],
    "🐛 Bug 修复": [],
    "🔧 工程化 / 重构 / 配置": [],
    "📚 调研 / 文档": [],
    "🔀 合并 / 其他": [],
}
for line in raw.splitlines():
    if not line or "|" not in line:
        continue
    sha, subj = line.split("|", 1)
    s = subj.strip()
    if s.startswith("feat") or "功能" in s and "docs" not in s.lower():
        groups["🆕 新功能 / 产品进展"].append((sha, s))
    elif s.startswith("fix") or "修复" in s:
        groups["🐛 Bug 修复"].append((sha, s))
    elif s.lower().startswith(("docs", "调研")) or "文档" in s or "调研" in s:
        groups["📚 调研 / 文档"].append((sha, s))
    elif s.startswith("Merge"):
        groups["🔀 合并 / 其他"].append((sha, s))
    else:
        groups["🔧 工程化 / 重构 / 配置"].append((sha, s))

print(f"# 开发日志素材（近 {DAYS} 天，自 {since}）\n")
for name, items in groups.items():
    print(f"## {name}（{len(items)} 条）\n")
    for sha, s in items:
        print(f"- `{sha}` {s}")
    print()

print("## Bug 状态（docs/22-bug）\n")
for f in sorted(os.listdir("docs/22-bug")):
    if not f.endswith(".md") or f == "00-README.md":
        continue
    p = os.path.join("docs/22-bug", f)
    mtime = datetime.date.fromtimestamp(os.path.getmtime(p))
    if (today - mtime).days <= DAYS:
        print(f"- {f}（{mtime} 更新）")
print()

print("## 一句话总览（自动提炼，可作日志开头）\n")
total = sum(len(v) for k, v in groups.items() if not k.startswith("🔀"))
feat = len(groups["🆕 新功能 / 产品进展"])
fix = len(groups["🐛 Bug 修复"])
eng = len(groups["🔧 工程化 / 重构 / 配置"])
if total:
    parts = []
    if feat:
        parts.append(f"{feat} 项功能/产品进展")
    if fix:
        parts.append(f"{fix} 项 bug 修复")
    if eng:
        parts.append(f"{eng} 项工程化")
    print(f"今天共 {total} 项提交：{'、'.join(parts)}。")
    print("值得展开讲的点（挑 1-2 个）：")
    for sha, s in (groups["🐛 Bug 修复"] + groups["🆕 新功能 / 产品进展"])[:3]:
        print(f"  - {s}")
else:
    print("今天暂无提交。")

#!/usr/bin/env python3
"""skill-ecommercial 质量门禁。

检查每个 skill 是否满足仓库约定（10 个维度）：
  1. 目录结构完整（SKILL.md + chapters/ + glossary.md + patterns.md + cheatsheet.md）
  2. frontmatter 合法，且 name 与目录名一致
  3. description 是单行字符串且足够触发
  4. SKILL.md 正文体量在预算内（默认 4000 tokens，且不能是空壳）
  5. chapters/ 非空，章节内容不过少、不过大
  6. cheatsheet.md 必须是决策内容，不能是空壳（要含决策标记 + 表格）
  7. glossary.md 条目数足够且逐条标注来源
  8. patterns.md 至少 3 条含「何时用」的方法，并标注代价/风险
  9. 无占位符残留（TODO / TBD / 待补充 / FIXME / lorem）
 10. 交叉引用的 skill 名都真实存在

退出码：0 = 全部通过；1 = 有 ERROR；2 = 用法错误。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_FILES = ("SKILL.md", "glossary.md", "patterns.md", "cheatsheet.md")
REQUIRED_DIRS = ("chapters",)

# CJK 约 1.6 字/token，ASCII 约 4 字符/token —— 取较保守的一侧估算
CJK_CHARS_PER_TOKEN = 1.6
ASCII_CHARS_PER_TOKEN = 4.0

PLACEHOLDERS = (
    "TODO", "TBD", "FIXME", "XXX", "待补充", "待完善", "占位符",
    "lorem ipsum", "Lorem ipsum", "示例文本", "PLACEHOLDER",
)

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
SKILL_REF_RE = re.compile(r"\[\[([a-z0-9][a-z0-9\-]*)\]\]")
DECISION_MARKERS = (
    "何时", "当", "如果", "则", "决策", "阈值", "判据", "≥", "≤", ">",
    "<", "建议", "不要", "必须", "优先",
)


def estimate_tokens(text: str) -> int:
    """按 CJK / ASCII 分别估算 token 数。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    other = len(text) - cjk
    return int(cjk / CJK_CHARS_PER_TOKEN + other / ASCII_CHARS_PER_TOKEN)


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    block, body = m.group(1), raw[m.end():]
    data: dict = {}
    key = None
    for line in block.splitlines():
        if re.match(r"^\s*-\s", line) or not line.strip():
            continue
        km = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", line)
        if km:
            key = km.group(1)
            val = km.group(2).strip()
            if val.startswith(("[", "{")):
                val = val.strip("[]{}").strip().strip("\"'")
            data[key] = val
        elif key and line.startswith((" ", "\t")):
            data[key] = (str(data.get(key, "")) + " " + line.strip()).strip()
    return data, body


def check_skill(skill_dir: Path, budget: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    name = skill_dir.name

    for fname in REQUIRED_FILES:
        if not (skill_dir / fname).is_file():
            errors.append(f"[{name}] 缺少必需文件 {fname}")
    for dname in REQUIRED_DIRS:
        if not (skill_dir / dname).is_dir():
            errors.append(f"[{name}] 缺少必需目录 {dname}/")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return errors, warns

    raw = skill_md.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)

    if not fm:
        errors.append(f"[{name}] SKILL.md 缺少 YAML frontmatter")
    else:
        if fm.get("name") != name:
            errors.append(f"[{name}] frontmatter name='{fm.get('name')}' 与目录名不一致")
        desc = fm.get("description", "")
        if not desc:
            errors.append(f"[{name}] frontmatter 缺 description")
        elif len(desc) < 20:
            errors.append(f"[{name}] description 过短（{len(desc)} 字符），不足以触发")
        elif "\n" in desc:
            warns.append(f"[{name}] description 含换行，建议压成单行")

    tokens = estimate_tokens(body)
    if tokens > budget:
        errors.append(f"[{name}] SKILL.md 正文约 {tokens} tokens，超出预算 {budget}")
    elif tokens < 200:
        warns.append(f"[{name}] SKILL.md 正文仅约 {tokens} tokens，可能是空壳")

    chapters_dir = skill_dir / "chapters"
    if chapters_dir.is_dir():
        chapters = sorted(chapters_dir.glob("*.md"))
        if not chapters:
            errors.append(f"[{name}] chapters/ 为空")
        for ch in chapters:
            ctext = ch.read_text(encoding="utf-8")
            if len(ctext.strip()) < 300:
                errors.append(f"[{name}] 章节 {ch.name} 内容过少（<300 字符）")
            if estimate_tokens(ctext) > 6000:
                warns.append(f"[{name}] 章节 {ch.name} 约 {estimate_tokens(ctext)} tokens，偏大")

    cheat = skill_dir / "cheatsheet.md"
    if cheat.is_file():
        ctext = cheat.read_text(encoding="utf-8")
        if len(ctext.strip()) < 300:
            errors.append(f"[{name}] cheatsheet.md 过短（<300 字符）")
        if not any(m in ctext for m in DECISION_MARKERS):
            warns.append(f"[{name}] cheatsheet.md 未见决策性内容标记，可能只是术语罗列")
        if "|" not in ctext:
            warns.append(f"[{name}] cheatsheet.md 无表格，建议用阈值表/决策树呈现")

    glossary = skill_dir / "glossary.md"
    if glossary.is_file():
        gtext = glossary.read_text(encoding="utf-8")
        if gtext.count("**") < 6:
            warns.append(f"[{name}] glossary.md 条目偏少")
        if "来源" not in gtext:
            warns.append(f"[{name}] glossary.md 条目未标注来源")

    patterns = skill_dir / "patterns.md"
    if patterns.is_file():
        ptext = patterns.read_text(encoding="utf-8")
        if ptext.count("**何时用**") < 3:
            warns.append(f"[{name}] patterns.md 少于 3 条含「何时用」的方法")
        if "**代价" not in ptext and "**风险" not in ptext:
            warns.append(f"[{name}] patterns.md 未标注代价/风险")

    for f in skill_dir.rglob("*.md"):
        ftext = f.read_text(encoding="utf-8")
        for ph in PLACEHOLDERS:
            if ph in ftext:
                warns.append(f"[{name}] {f.relative_to(skill_dir)} 含占位符「{ph}」")
                break

    return errors, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="skill-ecommercial 质量门禁")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="仓库根目录（默认取脚本上级目录）")
    ap.add_argument("--budget", type=int, default=4000,
                    help="SKILL.md 正文 token 预算（默认 4000）")
    ap.add_argument("--quiet", action="store_true", help="只输出问题，不输出通过信息")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        print(f"错误：找不到 {skills_dir}", file=sys.stderr)
        return 2

    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    if not skill_dirs:
        print("错误：skills/ 下没有任何含 SKILL.md 的 skill 目录", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    all_warns: list[str] = []
    for sd in skill_dirs:
        e, w = check_skill(sd, args.budget)
        all_errors += e
        all_warns += w

    known = {p.name for p in skill_dirs}
    for sd in skill_dirs:
        for f in sd.rglob("*.md"):
            for ref in SKILL_REF_RE.findall(f.read_text(encoding="utf-8")):
                if ref not in known:
                    all_warns.append(f"[{sd.name}] {f.relative_to(sd)} 引用了不存在的 skill [[{ref}]]")

    for w in all_warns:
        print(f"WARN  {w}")
    for e in all_errors:
        print(f"ERROR {e}")

    if not args.quiet:
        print(f"\n检查 {len(skill_dirs)} 个 skill："
              f"{len(all_errors)} error / {len(all_warns)} warn")

    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())

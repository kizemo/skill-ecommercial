#!/usr/bin/env python3
"""docs/技能备份/ 与 skills/ 的同步校验。

仓库里有一份「技能入口正文备份」：`docs/技能备份/<skill>/SKILL.md`。
它是 `skills/<skill>/SKILL.md` 的**同步副本**，唯一区别是相对链接被改写成
指向仓库权威副本（`../../skills/<skill>/...`），这样在 GitHub 上直接点开
备份文件也能跳到对应章节。

为什么要两份：
- `skills/` 是**权威副本**，宿主装的是它，门禁扫的是它；
- `docs/技能备份/` 是**可读副本**，给不装技能、只想在网页上翻的人看。

因为是副本，就必须有防漂移的门禁，否则副本会悄悄过期。本脚本就是那道门：
重新从 `skills/` 生成期望内容，逐字节比对 `docs/技能备份/`，不一致就报错退出。

用法：
    python scripts/verify_docs_backup.py            # 校验（CI 用），漂移退出码 1
    python scripts/verify_docs_backup.py --write    # 重新生成备份
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
BACKUP = REPO / "docs" / "技能备份"

# 只改写仓库内的相对链接（任意后缀，不只是 .md）；http(s)、锚点、绝对路径、mailto 一律不动
LINK_RE = re.compile(r"\]\((?!https?://|mailto:|#|/)([^)\s]+)\)")


def rewrite(text: str, skill: str) -> str:
    """把相对链接改写成指向 skills/ 权威副本的形式。

    备份文件在 `docs/技能备份/<skill>/SKILL.md`，仓库根在**三级**之上
    （`<skill>/` → `技能备份/` → `docs/` → 根），所以前缀是 `../../../skills/`。
    """
    def sub(m: re.Match[str]) -> str:
        target = m.group(1)
        return f"](../../../skills/{skill}/{target})"
    return LINK_RE.sub(sub, text)


def expected(skill: str) -> str:
    src = SKILLS / skill / "SKILL.md"
    return rewrite(src.read_text(encoding="utf-8"), skill)


def main() -> int:
    ap = argparse.ArgumentParser(description="校验 / 生成 docs/技能备份")
    ap.add_argument("--write", action="store_true", help="重新生成备份而不是校验")
    args = ap.parse_args()

    skills = sorted(p.name for p in SKILLS.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    if not skills:
        print("错误：skills/ 下没有可备份的技能", file=sys.stderr)
        return 2

    if args.write:
        BACKUP.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            dst = BACKUP / skill / "SKILL.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(expected(skill), encoding="utf-8")
        print(f"已生成 {len(skills)} 份备份 → {BACKUP.relative_to(REPO)}")
        return 0

    problems: list[str] = []
    have = sorted(p.name for p in BACKUP.iterdir() if p.is_dir()) if BACKUP.is_dir() else []
    for extra in set(have) - set(skills):
        problems.append(f"备份里有仓库中已不存在的技能：{extra}")

    for skill in skills:
        dst = BACKUP / skill / "SKILL.md"
        if not dst.is_file():
            problems.append(f"缺少备份：{dst.relative_to(REPO)}")
            continue
        want = expected(skill)
        got = dst.read_text(encoding="utf-8")
        if want != got:
            wl, gl = want.splitlines(), got.splitlines()
            diff_at = next((i for i, (a, b) in enumerate(zip(wl, gl)) if a != b),
                           min(len(wl), len(gl)))
            problems.append(
                f"备份与源不一致：{skill}（第 {diff_at + 1} 行起；"
                f"源 {len(wl)} 行 / 备份 {len(gl)} 行）")

    if problems:
        for p in problems:
            print(f"ERROR {p}")
        print(f"\n备份校验失败：{len(problems)} 处问题。"
              f"修完跑 `python scripts/verify_docs_backup.py --write` 重新生成。")
        return 1

    print(f"备份校验通过：{len(skills)} 本技能入口正文与 skills/ 逐字节一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""安装验收：检查宿主技能目录里的本仓技能是否与仓库逐文件一致。

与 `install_skills.py` 共用同一套宿主目录探测逻辑 —— 装到哪就查哪，
不会因为"机器上有两个配置根"而查错地方。

用法：
  python scripts/verify_install.py             # 查所有探测到的宿主
  python scripts/verify_install.py claude      # 只查 Claude Code
  python scripts/verify_install.py minimax     # 只查 MiniMax Code

判定项（每本技能）：
  1. 目录存在且含 SKILL.md
  2. 文件集合与仓库完全一致（多一个或少一个都算不一致）
  3. 每个文件的内容与仓库一致（SHA256）—— 挡住"文件同名但内容是旧版"
  4. SKILL.md 的 frontmatter 只有 name + description，且 name 与目录名一致

退出码：0 = 全部通过，1 = 有不一致，2 = 用法错误。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from install_skills import HOSTS, candidate_dirs, pick_dir  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SKILLS_SRC = REPO / "skills"

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
KEY_RE = re.compile(r"^([A-Za-z_-]+):", re.M)
NAME_RE = re.compile(r"^name:\s*(.+)$", re.M)


def skill_files(root: Path) -> list[Path]:
    """技能目录下的全部文件（排除 __pycache__ 与字节码）。"""
    return sorted(
        p.relative_to(root)
        for p in root.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix not in (".pyc", ".pyo")
    )


def file_manifest(root: Path) -> dict[str, str]:
    """相对路径 → SHA256。用来同时判"文件在不在"和"内容对不对"。"""
    out: dict[str, str] = {}
    for rel in skill_files(root):
        try:
            out[rel.as_posix()] = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        except OSError:
            out[rel.as_posix()] = "__unreadable__"
    return out


def manifest_diff(src: Path, dst: Path) -> tuple[list[str], list[str]]:
    """返回 (仅在一边存在的文件, 内容不同的文件)。"""
    a, b = file_manifest(src), file_manifest(dst)
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = sorted(k for k in (set(a) & set(b)) if a[k] != b[k])
    return only_a + only_b, changed


def frontmatter_ok(skill_md: Path, expected_name: str) -> bool:
    if not skill_md.is_file():
        return False
    m = FM_RE.match(skill_md.read_text(encoding="utf-8"))
    if not m:
        return False
    keys = KEY_RE.findall(m.group(1))
    if sorted(keys) != ["description", "name"]:
        return False
    nm = NAME_RE.search(m.group(1))
    return bool(nm) and nm.group(1).strip() == expected_name


def check_host(host: str, dest: Path, src_names: list[str]) -> list[str]:
    fails: list[str] = []
    print("=" * 78)
    print(f"宿主    : {host}  →  {dest}")
    print("=" * 78)

    if not dest.is_dir():
        print(f"  [跳过] 目录不存在：{dest}")
        return fails

    for name in src_names:
        src = SKILLS_SRC / name
        dst = dest / name
        if not dst.is_dir():
            fails.append(f"{host}: 缺少技能 {name}")
            print(f"  !!  {name:<24s} 未安装")
            continue
        only, changed = manifest_diff(src, dst)
        fm_ok = frontmatter_ok(dst / "SKILL.md", name)
        status = "OK " if (not only and not changed and fm_ok) else "!! "
        n_ch = len([f for f in skill_files(dst) if f.parts and f.parts[0] == "chapters"])
        print(f"  {status} {name:<24s} 文件 {len(skill_files(dst)):2d}  章 {n_ch}"
              + ("" if fm_ok else "  frontmatter异常")
              + ("" if not changed else f"  内容不同 {len(changed)} 个"))
        if only:
            fails.append(f"{host}: {name} 文件集合不一致（多/少：{[str(x) for x in only][:5]}）")
        if changed:
            fails.append(f"{host}: {name} 内容与仓库不一致（{[str(x) for x in changed][:5]}）")
        if not fm_ok:
            fails.append(f"{host}: {name} frontmatter 不是 name+description 或 name 与目录名不符")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description="校验宿主里的 skill-ecommercial 技能是否与仓库一致")
    ap.add_argument("host", nargs="?", choices=sorted(HOSTS) + ["all"], default="all",
                    help="只校验指定宿主（默认全部）")
    args = ap.parse_args()

    if not SKILLS_SRC.is_dir():
        print(f"[错误] 找不到 {SKILLS_SRC}", file=sys.stderr)
        return 2

    src_names = sorted(p.name for p in SKILLS_SRC.iterdir()
                       if p.is_dir() and (p / "SKILL.md").is_file())
    if not src_names:
        print("[错误] 仓库里没有可安装的技能", file=sys.stderr)
        return 2

    targets = sorted(HOSTS) if args.host == "all" else [args.host]
    all_fails: list[str] = []
    checked = 0

    for host in targets:
        dest = pick_dir(host, None)
        if not dest.is_dir():
            continue
        # 空壳目录（一个技能都没装）没有验收价值，跳过但提示
        populated = any((dest / n / "SKILL.md").is_file() for n in src_names)
        if not populated:
            print("=" * 78)
            print(f"宿主    : {host}  →  {dest}")
            print("=" * 78)
            print("  [跳过] 该目录下没有本仓技能（可能是空壳目录）")
            print()
            continue
        checked += 1
        all_fails += check_host(host, dest, src_names)
        print()

    if checked == 0:
        print("没有找到装过本仓技能的宿主目录 —— 先跑 install_skills.py 装一次。")
        return 1

    print("=" * 78)
    if all_fails:
        print("❌ 验收未通过：")
        for f in all_fails:
            print("   -", f)
        print()
        print("修复：重跑安装脚本并加 --force，装过的每个宿主都要跑一遍。")
        return 1
    print(f"✅ 验收通过：{checked} 个宿主、{len(src_names)} 本技能，文件与仓库一致、frontmatter 均为 name+description")
    return 0


if __name__ == "__main__":
    sys.exit(main())

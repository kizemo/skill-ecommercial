#!/usr/bin/env python3
"""把本仓库的 skills/ 安装到某个 AI 宿主的技能目录。

支持两类宿主（两者都读 Anthropic Agent Skills 开放格式：`<name>/SKILL.md` + frontmatter）：

  claude   Claude Code / Claude Code 桌面版（cc-haha 等自建 harness 也走这一套）
           Windows : %USERPROFILE%\\.claude\\skills
           macOS   : ~/.claude/skills
           Linux   : ~/.claude/skills

  minimax  MiniMax Code
           %MINIMAX_HOME%\\skills，默认 E:\\Users\\<user>\\.minimax\\.minimax\\skills
           也可用环境变量 MINIMAX_SKILLS_DIR 直接指定

用法：
  python scripts/install_skills.py --host claude --dry-run
  python scripts/install_skills.py --host claude
  python scripts/install_skills.py --host claude --only daily-store-patrol,store-diagnosis
  python scripts/install_skills.py --host minimax --mode symlink
  python scripts/install_skills.py --list-hosts

不写任何口令、不改宿主配置，只复制（或建符号链接）技能目录。
"""

import argparse
import datetime
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_SRC = REPO / "skills"

# Claude Code 配置根的判据：含 sessions/ 或 projects/ 或 .claude.json 的那个才算"配置根"。
# 本机实测 C:\Users\Duanyi\.claude 与 E:\Users\Duanyi\.claude 并存且都命中判据，
# 只能靠**最近修改时间**区分谁在活跃（桌面版每天都在写的那份）。
_ACTIVE_MARKERS = ("sessions", "projects", ".claude.json", "shell-snapshots")


def _is_active_claude_root(p: Path) -> bool:
    if not p.is_dir():
        return False
    return any((p / m).exists() for m in _ACTIVE_MARKERS)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _dedupe_by_realpath(paths: list[Path]) -> list[Path]:
    """按 realpath 去重。

    本机实测 C:\\Users\\Duanyi\\.claude 是指向 E:\\Users\\Duanyi\\.claude 的符号链接，
    两个路径其实是同一处；不 dedupe 会让用户以为要装两份。
    """
    out, seen = [], set()
    for p in paths:
        try:
            key = str(Path(os.path.realpath(p))).lower()
        except OSError:
            key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _claude_roots() -> list[Path]:
    """探测本机所有 Claude Code 配置根，最近被写过的排最前。"""
    found: list[Path] = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        found.append(Path(env).expanduser())
    for drive in "CDEFG":
        base = Path(f"{drive}:/Users")
        if not base.is_dir():
            continue
        for user_dir in base.iterdir():
            if not user_dir.is_dir():
                continue
            c = user_dir / ".claude"
            if _is_active_claude_root(c):
                found.append(c)
    home_claude = Path.home() / ".claude"
    if _is_active_claude_root(home_claude):
        found.append(home_claude)
    found = _dedupe_by_realpath(found)
    found.sort(key=lambda p: -_mtime(p))
    return found


def _minimax_roots() -> list[Path]:
    found: list[Path] = []
    env = os.environ.get("MINIMAX_SKILLS_DIR")
    if env:
        found.append(Path(env).expanduser())
    for drive in "CDEFG":
        base = Path(f"{drive}:/Users")
        if not base.is_dir():
            continue
        for user_dir in base.iterdir():
            if not user_dir.is_dir():
                continue
            c = user_dir / ".minimax" / ".minimax" / "skills"
            if c.is_dir():
                found.append(c)
    home = Path.home() / ".minimax" / ".minimax" / "skills"
    if home.is_dir():
        found.append(home)
    uniq, seen = [], set()
    for p in found:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return _dedupe_by_realpath(uniq)


# 宿主标识 -> (显示名, 候选目录列表)
HOSTS = {
    "claude": ("Claude Code / cc-haha", None),
    "minimax": ("MiniMax Code", None),
}


def candidate_dirs(host: str) -> list[Path]:
    if host == "claude":
        return [p / "skills" for p in _claude_roots()]
    return _minimax_roots()


def _looks_populated(p: Path) -> bool:
    """目录下已经有像样的技能（至少一个含 SKILL.md 的子目录）。"""
    try:
        for child in p.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                return True
    except OSError:
        pass
    return False


def pick_dir(host: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    cands = candidate_dirs(host)
    # 先要"有货"的目录，再要最近被写过的
    for p in cands:
        if p.exists() and _looks_populated(p):
            return p
    for p in cands:
        if p.exists():
            return p
    return cands[0] if cands else Path(host) / "skills"


def list_hosts():
    print("可用宿主与本机候选目录（★ = 推荐装这里）：\n")
    for host, (label, _) in HOSTS.items():
        print(f"[{host}] {label}")
        cands = candidate_dirs(host)
        if not cands:
            print("    （没探测到候选目录，可用 --dest 显式指定）")
        best = pick_dir(host, None)
        for p in cands:
            mark = "存在" if p.exists() else "不存在（会被创建）"
            n = len([c for c in p.iterdir()
                     if c.is_dir() and (c / "SKILL.md").is_file()]) if p.is_dir() else 0
            star = "★ " if str(p) == str(best) else "   "
            print(f"  {star}{p}   [{mark}]  已装 {n} 本")
        print()
    print("提示：★ 是脚本实际会写的位置。C 盘与 E 盘同时存在配置根时，")
    print("     以「已经装了技能的那个」为准 —— 有时其中一个是空壳或符号链接。")
    print()


def copy_tree(src: Path, dst: Path) -> None:
    """复制技能目录，跳过 __pycache__ / *.pyc。"""
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
        dirs_exist_ok=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="安装 skill-ecommercial 的技能到 AI 宿主")
    ap.add_argument("--host", choices=sorted(HOSTS) + ["auto"], default="auto",
                    help="目标宿主：claude / minimax / auto（默认 auto，按存在性挑）")
    ap.add_argument("--dest", help="显式指定目标目录，覆盖宿主默认路径")
    ap.add_argument("--only", help="只装指定技能（逗号分隔的名字）")
    ap.add_argument("--mode", choices=["copy", "symlink"], default="copy",
                    help="copy=复制（默认，任何平台都行）；symlink=建符号链接（省磁盘，Windows 需管理员）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做什么")
    ap.add_argument("--list-hosts", action="store_true", help="列出本机可用的宿主目录")
    ap.add_argument("--force", action="store_true", help="目标已存在时覆盖")
    args = ap.parse_args()

    if args.list_hosts:
        list_hosts()
        return 0

    if not SKILLS_SRC.is_dir():
        print(f"[错误] 找不到 {SKILLS_SRC}", file=sys.stderr)
        return 2

    names = sorted(p.name for p in SKILLS_SRC.iterdir() if p.is_dir())
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        missing = want - set(names)
        if missing:
            print(f"[错误] 仓库里没有这些技能：{', '.join(sorted(missing))}", file=sys.stderr)
            return 2
        names = [n for n in names if n in want]
    if not names:
        print("[错误] 没有可安装的技能", file=sys.stderr)
        return 2

    # auto：优先 claude，其次 minimax
    host = args.host
    if host == "auto":
        host = next((h for h in ("claude", "minimax")
                     if any(p.exists() for p in candidate_dirs(h))), "claude")

    dest = pick_dir(host, args.dest)
    label = HOSTS[host][0]

    print(f"宿主    : {host}（{label}）")
    print(f"目标目录: {dest}")
    print(f"技能数量: {len(names)}")
    print(f"安装方式: {args.mode}")
    print()

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    installed, skipped = [], []
    for n in names:
        src = SKILLS_SRC / n
        target = dest / n
        if target.exists() and not args.force:
            skipped.append(n)
            print(f"  [跳过] {n}（已存在，加 --force 覆盖）")
            continue
        if args.dry_run:
            installed.append(n)
            print(f"  [计划] {n}")
            continue
        try:
            if target.exists():
                shutil.rmtree(target)
            if args.mode == "symlink":
                os.symlink(src, target, target_is_directory=True)
            else:
                copy_tree(src, target)
            installed.append(n)
            print(f"  [完成] {n}")
        except OSError as e:
            print(f"  [失败] {n}：{e}", file=sys.stderr)

    print()
    print(f"新装 {len(installed)} 本，跳过 {len(skipped)} 本。")
    if installed:
        print()
        print("下一步：")
        if host == "claude":
            print("  · 重启 Claude Code / cc-haha，新技能才会被索引")
            print("  · 手动调用：/daily-store-patrol（不确定用哪本时先用 /skill-ecommercial 路由）")
        else:
            print("  · 重启 MiniMax Code，新技能才会被索引")
            print("  · 手动调用：/daily-store-patrol（不确定用哪本时先用 /skill-ecommercial 路由）")
        if args.mode == "copy":
            print("  · 以后更新仓库后，重跑本命令即可（加 --force 覆盖旧版本）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

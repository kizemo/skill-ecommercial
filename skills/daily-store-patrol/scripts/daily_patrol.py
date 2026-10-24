#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日巡店脚本 —— 读 PG（taobao 库 + erp 库），输出巡店报告（Markdown）。

数据源（全部为本机 PostgreSQL 真实表，实测 2026-10-24）：
  taobao.shop_<店>.core_daily_2026           店铺经营核心日报（124 列）
  taobao.shop_<店>.shop_traffic_source_2026   流量来源（含第一次/最后一次访问归因）
  taobao.shop_<店>.customer_assets_2026       客户资产（48 列）
  taobao.shop_<店>.wxt_promotion_baobei_2026   万相台·宝贝（货品）推广
  taobao.shop_<店>.wxt_promotion_keyword_2026  万相台·关键词推广
  taobao.shop_<店>.wxt_promotion_audience_2026 万相台·人群推广
  erp.erp_result.daily_sku_dd_2026            SKU 级日汇总（类型含"真实/补单"）
  erp.erp_result.daily_store_dd_2026          店铺级日汇总（含推广费用/营销费用/投产比）

三个已踩过的坑，脚本内已处理：
  1. 比率字段单位不统一 —— 同一列可能是"百分数"（1.53）也可能是"小数"（0.0153）。
     脚本按目标日期附近 7 天中位数自动判定单位并归一。
  2. core_daily 的"成功退款金额"是**当天发生的退款**（含历史订单退款），
     不能除当日支付金额当退款率。真实退款率要用 ERP 按**订单日期**的"退货金额"。
  3. 淘宝店铺在 ERP 的"推广费用"是 NULL —— 淘宝推广费从 taobao 库取，
     ERP 的推广费用只有 JD/PDD 等平台有值。

连接方式：读标准 libpq 环境变量（PGHOST / PGPORT / PGUSER / PGDATABASE / PGPASSWORD），
口令走 .pgpass 或 PGPASSWORD，本脚本不内置任何账号口令。

用法：
    python daily_patrol.py --shop all
    python daily_patrol.py --shop haoyale --date 2026-10-22
    python daily_patrol.py --shop all --out report.md
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import date, timedelta

try:
    import psycopg2
except ImportError:
    sys.exit("需要 psycopg2：pip install psycopg2-binary")

SHOP_SCHEMA_SUFFIXES = [
    "haoyale", "feite", "fengshangzhi", "renhe", "zhuoguang", "jiantai", "darong",
]

# (列名, 显示名, 方向)  方向: up=越大越好 / down=越小越好 / none=中性（花费类，不打灯）
CORE_METRICS = [
    ("访客数", "访客", "up"),
    ("支付金额", "支付金额", "up"),
    ("支付买家数", "成交人数", "up"),
    ("支付转化率", "支付转化率", "up"),
    ("客单价", "客单价", "up"),
    ("UV价值", "UV价值", "up"),
    ("跳失率", "跳失率", "down"),
    ("成功退款金额", "当日退款发生额", "none"),
    ("支付新买家数", "新客数", "up"),
    ("支付老买家数", "老客数", "up"),
    ("全站推广花费", "全站推广花费", "none"),
    ("关键词推广花费", "关键词推广花费", "none"),
    ("精准人群推广花费", "精准人群推广花费", "none"),
    ("智能场景花费", "智能场景花费", "none"),
    ("淘宝客佣金", "淘客佣金", "none"),
    ("描述相符评分", "描述相符评分", "up"),
    ("服务态度评分", "服务态度评分", "up"),
    ("物流服务评分", "物流服务评分", "up"),
]

# 比率型字段（需要单位归一）
# 注意：UV价值 是金额口径（支付金额 ÷ 访客数，单位元），不是比率，**不要**放进这个集合
RATE_FIELDS = {"支付转化率", "跳失率", "下单转化率"}


def conn(dbname: str):
    dsn = dict(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "postgres"),
        dbname=dbname,
        connect_timeout=10,
    )
    pwd = os.environ.get("PGPASSWORD")
    if pwd:
        dsn["password"] = pwd
    return psycopg2.connect(**dsn)


def num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(v, nd=2):
    f = num(v)
    return "—" if f is None else f"{f:,.{nd}f}"


def pct(a, b):
    fa, fb = num(a), num(b)
    if fa is None or fb is None or fb == 0:
        return None
    return fa / fb * 100


PLAN_KIND_ORDER = {"宝贝/货品": 0, "关键词": 1, "人群": 2}


def merge_plans(items):
    """按计划名归并万相台记录。

    同一个计划会同时落在宝贝/货品、关键词、人群三张表里（同一计划在不同维度的滚算，
    实测同一计划的花费与投产一致、新客数差 1 以内）。不归并会在行动清单里把同一个
    计划列成多个可加投对象，并让同一笔花费被当成多笔。
    归并规则：维度标签合并成「宝贝/货品+关键词」；花费/比率/计数一律取**最大值**
    （不累加同一笔钱，避免虚增）；结论按严重度排序去重。
    """
    merged = {}
    for it in items:
        plan = (it.get("plan") or "").strip()
        if not plan:
            continue
        slot = merged.setdefault(plan, {"plan": plan, "kinds": set(), "cost": 0.0,
                                        "metric": None, "extra": None, "pieces": []})
        slot["kinds"].add(it.get("kind") or "")
        cost = num(it.get("cost")) or 0.0
        if cost > slot["cost"]:
            slot["cost"] = cost
        for key in ("metric", "extra"):
            v = it.get(key)
            if isinstance(v, (int, float)) and (slot[key] is None or v > slot[key]):
                slot[key] = v
        for piece in (it.get("text") or "").split("；"):
            piece = piece.strip()
            if piece and piece != "—" and piece not in slot["pieces"]:
                slot["pieces"].append(piece)

    def sev(p):
        return 0 if p.startswith("🔴") else 1 if p.startswith("🟡") else 2

    out = []
    for slot in merged.values():
        kinds = sorted(slot["kinds"], key=lambda k: PLAN_KIND_ORDER.get(k, 99))
        out.append({"plan": slot["plan"], "kind": "+".join(kinds), "cost": slot["cost"],
                    "metric": slot["metric"], "extra": slot["extra"],
                    "text": "；".join(sorted(slot["pieces"], key=sev))})
    return out


def q(cur, sql, args=None):
    """执行查询；出错时回滚并返回 [('__error__', msg)]，不中断整体巡店。"""
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    except Exception as e:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return [("__error__", str(e)[:220])]


def table_exists(cur, schema, table):
    cur.execute(
        "select 1 from information_schema.tables where table_schema=%s and table_name=%s",
        (schema, table))
    return cur.fetchone() is not None


def latest_date(cur, schema, table, col="stat_date"):
    r = q(cur, f'select max("{col}") from "{schema}"."{table}"')
    if not r or r[0][0] == "__error__":
        return None
    return r[0][0]


def rate_unit(cur, schema, table, field, target_date, col="stat_date"):
    """判定比率字段的单位。

    返回 'pct'（库中已是百分数，如 1.53 表示 1.53%）
        或 'ratio'（库中是小数，如 0.0153 表示 1.53%）
    判定方法：目标日期 ±3 天窗口内非空值的中位数 —— >1 判 pct，<=1 判 ratio。
    """
    r = q(cur, f'''select "{field}" from "{schema}"."{table}"
                  where "{col}" between %s and %s and "{field}" is not null''',
          (target_date - timedelta(days=3), target_date + timedelta(days=3)))
    vals = [num(x[0]) for x in r if x[0] != "__error__"]
    vals = [v for v in vals if v is not None]
    if not vals:
        return "ratio", None
    med = statistics.median(vals)
    mixed = (max(vals) / min(vals) > 100) if min(vals) not in (0, None) else False
    return ("pct" if med > 1 else "ratio"), (med, mixed)


def to_pct(v, unit):
    f = num(v)
    if f is None:
        return None
    return f if unit == "pct" else f * 100


def with_unit(label, v):
    """按指标名补上单位后缀：比率型指标带 %，其余原样。

    汇总表与行动清单复用 lights 时必须带单位，否则「支付转化率 1.53」会被
    误读成小数，而大盘表里同一指标写的是「1.53%」。
    """
    s = fmt(v)
    return f"{s}%" if label in RATE_FIELDS and s != "—" else s


def light(cur_v, base_v, direction):
    """三色判定（对比自身 7 日均值）。

    up   越大越好：掉 10% 以内=绿，跌 10~25%=黄，跌超 25%=红
    down 越小越好：涨 10% 以内=绿，涨 10~25%=黄，涨超 25%=红
    none 中性：不打灯
    """
    a, b = num(cur_v), num(base_v)
    if direction == "none":
        if a is None or b is None or b == 0:
            return "—", "—"
        return "—", f"{(a - b) / abs(b) * 100:+.1f}%"
    if a is None or b is None or b == 0:
        return "黄", "无基线"
    delta = (a - b) / abs(b) * 100
    if direction == "up":
        if delta >= -10:
            return "绿", f"{delta:+.1f}%"
        if delta >= -25:
            return "黄", f"{delta:+.1f}%"
        return "红", f"{delta:+.1f}%"
    # direction == "down"
    if delta <= 10:
        return "绿", f"{delta:+.1f}%"
    if delta <= 25:
        return "黄", f"{delta:+.1f}%"
    return "红", f"{delta:+.1f}%"


def report_shop(sfx: str, want_date):
    lines = []

    def hdr(t):
        lines.extend(["", t, ""])

    tao = conn("taobao")
    erp = conn("erp")
    tcur, ecur = tao.cursor(), erp.cursor()
    schema = f"shop_{sfx}"
    traffic_rows = None
    asset = None
    asset_hist = None

    shop_name = sfx
    r = q(tcur, f'select distinct "店铺名称" from "{schema}"."core_daily_2026"')
    if r and r[0][0] != "__error__" and r[0][0]:
        shop_name = r[0][0]
    lines.append(f"# {shop_name}　(`{schema}`)")

    # ---------- 0. 数据新鲜度 ----------
    hdr("## 0 · 数据新鲜度（先确认数据到位，再谈巡店）")
    lines.append("| 数据源 | 最新日期 | 行数 | 状态 |")
    lines.append("|---|---|---|---|")
    fresh = {}
    for label, tbl in (("core_daily 店铺日报", "core_daily_2026"),
                       ("shop_traffic_source 流量来源", "shop_traffic_source_2026"),
                       ("customer_assets 客户资产", "customer_assets_2026"),
                       ("wxt_baobei 宝贝推广", "wxt_promotion_baobei_2026"),
                       ("wxt_keyword 关键词推广", "wxt_promotion_keyword_2026"),
                       ("wxt_audience 人群推广", "wxt_promotion_audience_2026")):
        if not table_exists(tcur, schema, tbl):
            lines.append(f"| {label} | 表不存在 | — | ⚠️ 缺表 |")
            continue
        d = latest_date(tcur, schema, tbl)
        n = q(tcur, f'select count(*) from "{schema}"."{tbl}"')
        cnt = n[0][0] if n and n[0][0] != "__error__" else "?"
        fresh[label] = d
        lines.append(f"| {label} | {d or '无数据'} | {cnt} | {'✅' if d else '⚠️ 空表'} |")
    d_erp = latest_date(ecur, "erp_result", "daily_sku_dd_2026", "订单日期") \
        if table_exists(ecur, "erp_result", "daily_sku_dd_2026") else None
    lines.append(f"| erp daily_sku_dd SKU 日汇总 | {d_erp or '无数据'} | — | "
                 f"{'✅' if d_erp else '⚠️'} |")
    lines.append("")
    lines.append("> ⚠️ **各源更新节奏不同**：店铺日报领先 ERP 约 4 天、领先万相台约 3 周。"
                 "结论只能基于各源自己的最新日期；**跨源对比前先确认日期是否对齐**，"
                 "不要把店铺日报的今日数和 ERP 的今日数放在同一张表里比。")

    if not table_exists(tcur, schema, "core_daily_2026"):
        lines.append("（缺 core_daily_2026，无法巡店）")
        tao.close(); erp.close()
        return shop_name, lines, False

    d_latest = latest_date(tcur, schema, "core_daily_2026")
    d_target = want_date or d_latest
    if d_target is None:
        lines.append("（core_daily 无数据）")
        tao.close(); erp.close()
        return shop_name, lines, False

    # ---------- 1. 店铺大盘 ----------
    hdr("## 1 · 店铺大盘（红绿灯 = 对比自身 7 日均值）")
    lines.append(f"统计日期 **{d_target}**｜基线 = 前 7 日同字段均值｜")
    lines.append("")
    lines.append("| 指标 | 当日 | 前一日 | 7日均值 | vs 基线 | 灯 |")
    lines.append("|---|---|---|---|---|---|")

    cols = ", ".join(f'"{c}"' for c, _, _ in CORE_METRICS)
    row_today = q(tcur, f'select {cols} from "{schema}"."core_daily_2026" where stat_date=%s', (d_target,))
    row_prev = q(tcur, f'select {cols} from "{schema}"."core_daily_2026" where stat_date=%s',
                 (d_target - timedelta(days=1),))
    base_rows = q(tcur, f'select {cols} from "{schema}"."core_daily_2026" '
                        f'where stat_date > %s and stat_date < %s order by stat_date desc limit 7',
                   (d_target - timedelta(days=8), d_target))
    if not row_today or row_today[0][0] == "__error__":
        lines.append(f"（{d_target} 无 core_daily 记录）")
        tao.close(); erp.close()
        return shop_name, lines, False

    # 比率字段单位自适应
    units = {}
    unit_notes = []
    for fld in RATE_FIELDS:
        u, info = rate_unit(tcur, schema, "core_daily_2026", fld, d_target)
        units[fld] = u
        if info and info[1]:
            unit_notes.append(f"`{fld}` 窗口内单位不一致（可能源文件切换），已按中位数归一，需人工复核")

    def val(row, i):
        fld, _, _ = CORE_METRICS[i]
        v = num(row[i]) if len(row) > i else None
        return to_pct(v, units.get(fld, "pct")) if fld in RATE_FIELDS else v

    def base_avg(i):
        vals = [val(r, i) for r in base_rows if len(r) > i]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    lights = []
    for i, (fld, label, direction) in enumerate(CORE_METRICS):
        cv = val(row_today[0], i)
        pv = val(row_prev[0], i) if row_prev else None
        bv = base_avg(i)
        color, note = light(cv, bv, direction)
        is_rate = fld in RATE_FIELDS
        nd = 2 if is_rate else 2
        lights.append((label, cv, bv, color, note, direction))
        lines.append(f"| {label} | {fmt(cv, nd)}{'%' if is_rate else ''} | "
                     f"{fmt(pv, nd)}{'%' if is_rate else ''} | {fmt(bv, nd)}{'%' if is_rate else ''} | "
                     f"{note} | {'🟢 绿' if color == '绿' else '🟡 黄' if color == '黄' else '🔴 红' if color == '红' else '— 中性'} |")
    for n in unit_notes:
        lines.append("")
        lines.append(f"> ⚠️ {n}")

    # 派生指标
    paid = val(row_today[0], 1)
    buyers = val(row_today[0], 2)
    newb = val(row_today[0], 8)
    oldb = val(row_today[0], 9)
    ad = sum(val(row_today[0], i) or 0 for i in (10, 11, 12, 13))
    commission = val(row_today[0], 14)
    refund_cash = val(row_today[0], 7)

    lines.append("")
    lines.append("**派生指标（同一表同日，口径自洽）**")
    lines.append("")
    lines.append("| 指标 | 算式 | 当日值 | 判读 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 推广费比 | 四项推广花费合计 ÷ 支付金额 | {fmt(pct(ad, paid))}% | "
                 "费比高说明利润薄；**先验投产真伪再谈加不加预算**（`profit-model`） |")
    lines.append(f"| 新客占比 | 支付新买家数 ÷ 支付买家数 | {fmt(pct(newb, buyers))}% | "
                 "⚠️ **人数口径**，7 店实测全部 ≥86%，判别力低；领先率要看第 3 节客户资产表的"
                 "**金额口径**（`store-diagnosis`） |")
    lines.append(f"| 老客占比 | 支付老买家数 ÷ 支付买家数 | {fmt(pct(oldb, buyers))}% | "
                 "老客占比过高 = 拉新链路断了 |")
    lines.append(f"| 佣金占比 | 淘客佣金 ÷ 支付金额 | {fmt(pct(commission, paid))}% | "
                 "淘客佣金是被动成本，计入真实投产 |")
    lines.append(f"| 当日退款发生额 | core_daily 成功退款金额 | {fmt(refund_cash)} | "
                 "⚠️ **这是当天发生的退款（含历史订单退款），不是当期退款率**，只能看趋势 |")
    lines.append("")

    # ---------- 2. 流量结构 ----------
    if table_exists(tcur, schema, "shop_traffic_source_2026"):
        hdr("## 2 · 流量结构（判断问题在哪一层）")
        rows = q(tcur, f'''select "归属原则", "二级流量来源", sum("访客数"), sum("支付金额"),
                                   sum("支付买家数"), sum("加购人数"), sum("收藏人数")
                            from "{schema}"."shop_traffic_source_2026"
                            where stat_date=%s group by 1,2
                            order by 3 desc nulls last limit 36''', (d_target,))
        if rows and rows[0][0] != "__error__":
            traffic_rows = rows
            lines.append("| 归属原则 | 二级来源 | 访客 | 支付金额 | 支付买家 | 转化率 | 加购人数 |")
            lines.append("|---|---|---|---|---|---|---|")
            for r in rows:
                prin, src = r[0], r[1]
                uv, amt, by, cart = num(r[2]), num(r[3]), num(r[4]), num(r[5])
                lines.append(f"| {prin} | {src} | {fmt(uv,0)} | {fmt(amt)} | {fmt(by,0)} | "
                             f"{fmt(pct(by, uv))}% | {fmt(cart,0)} |")
            lines.append("")
            lines.append("> **归属原则三选一，不可混用**：第一次访问来源 = 拉新链路；"
                         "最后一次访问来源 = 收割链路；每一次访问来源 = 总量口径。")
            lines.append("> 判读：把「第一次」和「最后一次」两组的支付买家数占比放一起比 —— "
                         "后者远高 ⇒ 在跑收割型定向（`store-diagnosis` 归因切换法）。")
        else:
            lines.append(f"（查询失败：{rows[0][1] if rows else '无数据'}）")

    # ---------- 3. 客户资产 ----------
    if table_exists(tcur, schema, "customer_assets_2026"):
        hdr("## 3 · 客户资产（看厚度与健康）")
        # 只查库里真实存在的列。`成交新客占比` / `入会率` / `引导访问量` 这类字段只存在于
        # wxt_promotion_* 表，customer_assets_2026 里没有 —— 查了会让整个 SELECT 报错、
        # 整段客户资产静默变空。
        cols_a = ('"用户数","未购买用户数","已购用户数","新访客户数","潜在客户数",'
                  '"已购客户回访数","180天复购率","总粉丝数","活跃粉丝数","沉睡粉丝数",'
                  '"机会粉丝数","新访客&已购支付金额","未购买&购买支付金额","已购&回购支付金额",'
                  '"新访客&已购用户数","未购买&购买用户数","已购&回购用户数",'
                  '"潜在客户新访客户数","已购客户数","父订单数","复购父订单数"')
        r = q(tcur, f'select {cols_a} from "{schema}"."customer_assets_2026" '
                    f'where stat_date=%s', (d_target,))
        if r and r[0][0] != "__error__" and len(r[0]) > 1:
            v = r[0]
            asset = v
            rp = num(v[6])
            # 三段拆解：金额三项 / 人数三项（实测与 core_daily 的支付金额、支付买家数完全对齐）
            amt_new, amt_pot, amt_rep = num(v[11]), num(v[12]), num(v[13])
            cnt_new, cnt_pot, cnt_rep = num(v[14]), num(v[15]), num(v[16])
            amt_sum = (amt_new or 0) + (amt_pot or 0) + (amt_rep or 0)
            cnt_sum = (cnt_new or 0) + (cnt_pot or 0) + (cnt_rep or 0)
            rate_amt = pct(amt_new, amt_sum) if amt_sum else None
            rate_cnt = pct(cnt_new, cnt_sum) if cnt_sum else None
            rate_newb = pct(newb, buyers)

            lines.append("| 指标 | 值 | 看什么 |")
            lines.append("|---|---|---|")
            for label, val_, note in (
                ("用户总数", v[0], "池子大小（当日口径）"),
                ("新访客户数", v[3], "拉新入口的量"),
                ("潜客中的新访客", v[17], "到过店还没成交的那部分新客"),
                ("已购客户数（累计）", v[18], "⚠️ 累计口径，**不是**当日成交人数"),
                ("潜在客户数", v[4], "⚠️ 平台级累计量，量级远大于本店主数据，"
                                   "**不可与已购客户数做比值**"),
                ("已购客户回访数", v[5], "回访有没有发生"),
                ("180天复购率", f"{fmt(rp*100)}%" if rp is not None else "—", "复购健康度"),
                ("总粉丝数", v[7], "私域池"),
                ("活跃粉丝", v[8], "触达得到"),
                ("沉睡粉丝", v[9], "召回对象"),
                ("机会粉丝", v[10], "可激活"),
                ("复购父订单占比", f"{fmt(pct(v[20], v[19]))}%", "复购强度"),
            ):
                lines.append(f"| {label} | {val_ if isinstance(val_, str) else fmt(val_)} | {note} |")
            lines.append("")
            lines.append("**成交拆解（新客 / 潜客首购 / 老客回购）**")
            lines.append("")
            lines.append("| 分段 | 人数 | 支付金额 |")
            lines.append("|---|---|---|")
            lines.append(f"| 新访客成交（新客） | {fmt(cnt_new,0)} | {fmt(amt_new)} |")
            lines.append(f"| 潜客首购 | {fmt(cnt_pot,0)} | {fmt(amt_pot)} |")
            lines.append(f"| 老客回购 | {fmt(cnt_rep,0)} | {fmt(amt_rep)} |")
            lines.append(f"| **合计** | **{fmt(cnt_sum,0)}** | **{fmt(amt_sum)}** |")
            lines.append(f"| core_daily 对照 | {fmt(buyers,0)} | {fmt(paid)} |")
            lines.append("")
            lines.append(f"- 新客成交金额占比（**金额口径领先率**）= **{fmt(rate_amt)}%**"
                         f"（`新访客&已购支付金额` ÷ 金额合计）")
            lines.append(f"- 严格新客人数占比 = {fmt(rate_cnt)}%"
                         f"（`新访客&已购用户数` ÷ 人数合计）")
            lines.append(f"- 大盘表新客占比（**人数口径**）= {fmt(rate_newb)}%"
                         f"（`支付新买家数` ÷ `支付买家数`）")
            lines.append("")
            if (rate_amt is not None and rate_newb is not None
                    and abs(rate_amt - rate_newb) > 15):
                lines.append(f"> ⚠️ **口径冲突，需复核**：同一笔成交金额拆开看，新客只占 "
                             f"{fmt(rate_amt)}%，而大盘表的人数口径是 {fmt(rate_newb)}%。"
                             f"两者不是同一个指标 —— **别拿人数口径当领先率判拉新/收割**，"
                             f"金额口径才是「新客成交 ÷ 总成交」（`store-diagnosis`）。")
                lines.append("")
            lines.append("> 沉睡粉丝 ≥ 活跃粉丝 = 私域未激活，今日排召回（`customer-asset-ops`）；"
                         "180天复购率 < 3% = 复购是存量生意。")
            # 自身 7 日基线（用于回访等相对判定；与大盘红绿灯同一套方法）
            asset_hist = q(tcur, f'''select "沉睡粉丝数","活跃粉丝数","180天复购率","已购客户回访数"
                                    from "{schema}"."customer_assets_2026"
                                    where stat_date < %s and stat_date > %s
                                    order by stat_date desc limit 7''',
                           (d_target, d_target - timedelta(days=8)))
        else:
            lines.append(f"（{d_target} 无客户资产记录）")

    # ---------- 4. 推广计划体检 ----------
    hdr("## 4 · 推广计划体检")
    lines.append("| 推广类型 | 计划 | 花费 | 直接成交 | 间接成交 | 投产 | 新客数 | 判读 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    findings = []
    winners = []
    for tbl, kind in (("wxt_promotion_baobei_2026", "宝贝/货品"),
                      ("wxt_promotion_keyword_2026", "关键词"),
                      ("wxt_promotion_audience_2026", "人群")):
        if not table_exists(tcur, schema, tbl):
            continue
        d = latest_date(tcur, schema, tbl)
        if d is None:
            continue
        rows = q(tcur, f'''select "计划名字", sum("花费"), sum("直接成交金额"), sum("间接成交金额"),
                                    sum("成交新客数"), sum("展现量"), sum("点击量"), sum("点击率")
                             from "{schema}"."{tbl}" where stat_date=%s
                             group by 1 order by 2 desc nulls last limit 12''', (d,))
        if not rows or rows[0][0] == "__error__":
            continue
        for r in rows:
            plan = r[0]
            cost, direct, indirect = num(r[1]), num(r[2]), num(r[3])
            newcust, imp, clk = num(r[4]) or 0, num(r[5]), num(r[6])
            roias = (direct + (indirect or 0)) / cost if cost and cost > 0 else None
            v = []
            if cost and cost > 0 and (direct or 0) == 0:
                v.append("🔴 有花费无直接成交")
            if direct and indirect and indirect / direct >= 2:
                v.append("🔴 间接≥2倍直接=投放无效")
            if roias is not None and cost and cost > 0 and roias < 1:
                v.append("🔴 投产<1")
            if roias and roias >= 1.5 and newcust == 0:
                v.append("🟡 只收割不拉新")
            if roias and roias >= 3 and newcust > 0:
                v.append("🟢 投产达标且带新客")
            if imp and clk is not None:
                ctr = pct(clk, imp)
                if ctr is not None and ctr < 1:
                    v.append("🟡 点击率<1%")
            txt = "；".join(v) if v else "—"
            lines.append(f"| {kind} | {plan} | {fmt(cost)} | {fmt(direct)} | {fmt(indirect)} | "
                         f"{fmt(roias)} | {fmt(newcust,0)} | {txt} |")
            if v and v[0].startswith("🔴"):
                findings.append({"kind": kind, "plan": plan, "cost": cost, "text": txt})
            if roias and roias >= 3 and newcust > 0 and cost and cost > 0:
                winners.append({"kind": kind, "plan": plan, "cost": cost,
                                "metric": roias, "extra": newcust})
    findings = merge_plans(findings)
    winners = merge_plans(winners)
    lines.append("")
    lines.append(f"> 万相台数据最新日期：{', '.join(sorted({str(latest_date(tcur, schema, t)) for t in ('wxt_promotion_baobei_2026','wxt_promotion_keyword_2026','wxt_promotion_audience_2026') if table_exists(tcur, schema, t)}))}"
                 "（比店铺日报滞后约 3 周，**不能当成昨日数据用**）")
    lines.append("> 投产比此处用（直接+间接）成交 ÷ 花费近似；平台自带 `投入产出比` 字段口径可能不同，"
                 "最终以平台字段为准。")
    lines.append("> 判读红线（知识库）：**间接成交 = 直接成交 2 倍 ⇒ 该品投放完全无效**。")
    lines.append("> ⚠️ 同一个计划可能同时出现在宝贝/货品、关键词、人群三张表里（同一计划的不同维度"
                 "滚算，花费与投产一致、新客数差 1 以内）。上表按原样列出便于对照，"
                 "**下方行动清单与机会清单已按计划名归并，同一计划只算一次**。")

    # ---------- 5. 商品层巡检 ----------
    hdr("## 5 · 商品层巡检（ERP · 已剔除「补单」）")
    if table_exists(ecur, "erp_result", "daily_sku_dd_2026"):
        lines.append(f"ERP 最新日期 **{d_erp}**（低于店铺日报属正常：ERP 同步滞后约 4 天）")
        lines.append("")
        lines.append("| 商品编码 | 销售金额 | 销售数量 | 退货数量 | 退货金额 | 退货率 | 成本/实收 | 判读 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        rows = q(ecur, '''select "商品编码", sum("销售金额"), sum("销售数量"), sum("退货数量"),
                                 sum("退货金额"), sum("商家实收"), sum("销售成本")
                          from erp_result.daily_sku_dd_2026
                          where "订单日期"=%s and "类型"='真实'
                          group by 1 order by 2 desc nulls last limit 25''', (d_erp,))
        if rows and rows[0][0] != "__error__":
            sku_bad = []
            for r in rows:
                code = r[0]
                amt, qty, rq, ramt = num(r[1]), num(r[2]), num(r[3]), num(r[4])
                recv, cost = num(r[5]), num(r[6])
                rr = pct(rq, qty) if qty else None
                cr = pct(cost, recv) if recv else None
                v = []
                if rr is not None and rr >= 20:
                    v.append("🔴 退货率≥20%")
                if cr is not None and cr > 100:
                    v.append("🔴 成本倒挂")
                if amt and amt > 0 and (qty or 0) == 0:
                    v.append("🟡 有金额无件数")
                txt = "；".join(v) if v else "—"
                lines.append(f"| {code} | {fmt(amt)} | {fmt(qty,0)} | {fmt(rq,0)} | {fmt(ramt)} | "
                             f"{fmt(rr)}% | {fmt(cr)}% | {txt} |")
                if v:
                    sku_bad.append((code, amt, txt))
            lines.append("")
            lines.append("> **退货率与成本倒挂是硬红线**：成本倒挂 = 卖一单亏一单，先停投再查原因"
                         "（`pricing-margin` / `compliance-medical`）。")
        else:
            lines.append(f"（查询失败：{rows[0][1] if rows else '无数据'}）")

        # 店铺级利润视角
        lines.append("")
        lines.append("**店铺级利润视角（ERP 同期口径）**")
        lines.append("")
        lines.append("| 店铺 | 销售金额 | 商家实收 | 销售成本 | 退货金额 | 退款率 | 推广费用 | 营销费用 | 投产比 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        rows = q(ecur, '''select "店铺", sum("销售金额"), sum("商家实收"), sum("销售成本"),
                                 sum("退货金额"), sum("推广费用"), sum("营销费用"),
                                 max("投入产出比")
                          from erp_result.daily_store_dd_2026
                          where "订单日期"=%s and "类型"='真实'
                          group by 1 order by 2 desc''', (d_erp,))
        if rows and rows[0][0] != "__error__":
            for r in rows:
                lines.append(f"| {r[0]} | {fmt(r[1])} | {fmt(r[2])} | {fmt(r[3])} | {fmt(r[4])} | "
                             f"{fmt(pct(r[4], r[1]))}% | {fmt(r[5])} | {fmt(r[6])} | {fmt(r[7])} |")
            lines.append("")
            lines.append("> ⚠️ 淘宝店铺的 **推广费用在 ERP 侧为 NULL**（淘宝推广费在 taobao 库的 "
                         "core_daily 四项推广花费里）。此表的推广费用只有 JD/PDD 等平台有值。")
            lines.append("> 退款率按**订单日期**同期口径计算（当天下单、最终退），"
                         "与 core_daily 的「当日退款发生额」不是一个口径，两者不要混用。")
        else:
            lines.append(f"（查询失败：{rows[0][1] if rows else '无数据'}）")
    else:
        lines.append("（erp 库不可用，跳过）")

    # ---------- 6. 结论 ----------
    hdr("## 6 · 结论：红绿灯汇总 + 今日行动清单")
    lines.append("| 指标 | 当日 | 7日均值 | 灯 |")
    lines.append("|---|---|---|---|")
    for label, cv, bv, color, note, direction in lights:
        if direction == "none":
            continue
        lines.append(f"| {label} | {with_unit(label, cv)} | {with_unit(label, bv)} | "
                     f"{'🟢 绿' if color=='绿' else '🟡 黄' if color=='黄' else '🔴 红'} |")
    lines.append("")
    lines.append("### 今日行动清单")
    lines.append("")
    actions = []
    for label, cv, bv, color, note, direction in lights:
        if color == "红":
            actions.append(f"🔴 **{label}** {with_unit(label, cv)}"
                           f"（7日均值 {with_unit(label, bv)}，{note}）→ 进专项诊断")
    for f in findings[:8]:
        actions.append(f"🔴 **推广计划 · {f['kind']} · {f['plan']}**（花费 {fmt(f['cost'])}）"
                       f"→ {f['text']}")
    if not actions:
        actions.append("🟢 无红灯项：保持节奏，把精力转向机会项。")
    lines.extend(f"- {a}" for a in actions)
    lines.append("")
    lines.append("")
    lines.append("### 机会项提示（由数据实算，非固定清单）")
    lines.append("")
    opps = []

    # 机会 1 · 费比相对基线
    base_ad = sum(base_avg(i) or 0 for i in (10, 11, 12, 13))
    base_paid = base_avg(1)
    base_feibi = pct(base_ad, base_paid)
    cur_feibi = pct(ad, paid)
    if base_feibi is not None and cur_feibi is not None:
        if cur_feibi < base_feibi * 0.95:
            opps.append(f"💰 **费比 {fmt(cur_feibi)}% 低于 7 日均值 {fmt(base_feibi)}%** "
                        f"→ 有预算回收空间，可加投赢家（`wanxiangtai-wujie`）")
        elif cur_feibi > base_feibi * 1.05:
            opps.append(f"⚠️ 费比 {fmt(cur_feibi)}% 已高于 7 日均值 {fmt(base_feibi)}% —— "
                        f"先验投产真伪再决定加不加（`profit-model`）")

    # 机会 2 · 高效率流量来源（每一次访问来源口径）
    if traffic_rows:
        tot_uv = sum(num(r[2]) or 0 for r in traffic_rows
                     if r[0] == "每一次访问来源")
        tot_by = sum(num(r[4]) or 0 for r in traffic_rows
                     if r[0] == "每一次访问来源")
        shop_cvr = pct(tot_by, tot_uv)
        if shop_cvr:
            cand = []
            for r in traffic_rows:
                if r[0] != "每一次访问来源":
                    continue
                uv, by = num(r[2]), num(r[4])
                if not uv or uv < 200 or not by:
                    continue
                cvr = pct(by, uv)
                if cvr and cvr >= shop_cvr * 1.5:
                    cand.append((r[1], uv, cvr, by))
            cand.sort(key=lambda x: -x[2])
            for src, uv, cvr, by in cand[:3]:
                opps.append(f"📈 **「{src}」转化率 {fmt(cvr)}%**（店铺均值 {fmt(shop_cvr)}%，"
                            f"访客 {fmt(uv,0)}）→ 被低估的来源，可加预算（`keyword-promo`）")

    # 机会 3 · 收割信号（领先率四档 —— 用客户资产表的**金额口径**）
    # 注意：core_daily 的 人数口径 新客占比在 7 家店里全部落在 86~91%，判别力接近零，
    # 只能当"新客结构是否正常"的粗筛，真正的领先率判读看下面的金额口径。
    nr = pct(newb, buyers)
    if nr is not None and nr >= 80:
        opps.append(f"✅ 大盘新客占比 {fmt(nr)}%（人数口径）达合格线 —— 但该口径在 7 店实测"
                    f"普遍 ≥86%，**判别力低**，拉新/收割以金额口径为准（见下）")
    if asset:
        amt_new, amt_pot, amt_rep = num(asset[11]), num(asset[12]), num(asset[13])
        cnt_new, cnt_pot, cnt_rep = num(asset[14]), num(asset[15]), num(asset[16])
        amt_sum = (amt_new or 0) + (amt_pot or 0) + (amt_rep or 0)
        rate_amt = pct(amt_new, amt_sum) if amt_sum else None
        if rate_amt is not None:
            if rate_amt >= 80:
                opps.append(f"✅ **新客成交金额占比 {fmt(rate_amt)}%**（金额口径领先率，≥80%）"
                            f"→ 拉新链路健康，保持（`store-diagnosis`）")
            elif rate_amt >= 70:
                opps.append(f"✅ **新客成交金额占比 {fmt(rate_amt)}%**（70-80%）→ "
                            f"头部 KA 可接受区间，继续积累人群资产")
            elif rate_amt >= 50:
                opps.append(f"🟡 **新客成交金额占比 {fmt(rate_amt)}%**（50-70%）→ "
                            f"资源浪费在收割，查定向与出价（`store-diagnosis`）")
            else:
                opps.append(f"🔴 **新客成交金额占比 {fmt(rate_amt)}%**（<50%）→ "
                            f"主要在跑收割，需开拉新计划"
                            f"（`customer-asset-ops` + `wanxiangtai-wujie`）")

    # 机会 4 · 私域召回 / 回访 / 复购
    if asset:
        sleep_f = num(asset[9])
        active_f = num(asset[8])
        rp = num(asset[6])
        visit = num(asset[5])
        if sleep_f and active_f and sleep_f >= active_f * 2:
            opps.append(f"💤 **沉睡粉丝 {fmt(sleep_f,0)} 是活跃粉丝 {fmt(active_f,0)} 的 "
                        f"{fmt(sleep_f/active_f,1)} 倍** → 私域基本没唤醒，今日排召回"
                        f"（`customer-asset-ops`）")
        elif sleep_f and active_f and sleep_f >= active_f:
            opps.append(f"💤 **沉睡粉丝 {fmt(sleep_f,0)} ≥ 活跃粉丝 {fmt(active_f,0)}**"
                        f" → 私域未激活，今日排召回（`customer-asset-ops`）")
        # 回访用**自身 7 日均值**做相对判定：回访数 ÷ 累计已购客户数在 7 家店里全部 <1%，
        # 绝对阈值没有区分度。
        if asset_hist and visit is not None:
            hist = [num(x[3]) for x in asset_hist if x and num(x[3]) is not None]
            if hist:
                bv = sum(hist) / len(hist)
                if bv and visit < bv * 0.7:
                    opps.append(f"👣 **已购客户回访数 {fmt(visit,0)} 较 7 日均值 {fmt(bv,0)} "
                                f"下降 {fmt((1-visit/bv)*100)}%** → 回访掉头，今日排触达"
                                f"（`customer-asset-ops`）")
        if rp is not None and rp < 0.03:
            opps.append(f"🔁 **180天复购率仅 {fmt(rp*100)}%** → 复购是存量生意，"
                        f"做老客运营（`customer-asset-ops`）")

    # 机会 5 · 加投候选计划（已按计划名归并，同一计划只出现一次）
    for w in sorted(winners, key=lambda x: -(x["metric"] or 0))[:3]:
        opps.append(f"🚀 **加投候选 · {w['kind']} · {w['plan']}**（投产 {fmt(w['metric'])}、"
                    f"新客 {fmt(w['extra'],0)}、花费 {fmt(w['cost'])}）→ 加预算，增幅 ≤50%"
                    f"（`wanxiangtai-wujie`）")

    if opps:
        lines.extend(f"- {o}" for o in opps)
    else:
        lines.append("- （本次未识别到明确的增量信号；绿灯状态下以维持节奏为主）")
    lines.append("")
    lines.append("> 潜力品（ERP 商品编码 ↔ 万相台宝贝ID **两套编码未对齐**）需人工映射，"
                 "本轮未自动识别 —— 见 `chapters/ch04-重点商品与计划筛选.md`。")
    lines.append("")
    lines.append("> **阈值口径**：红/黄/绿全部是**与自身 7 日均值**的相对判定，不含编造的绝对值；"
                 "绝对红线（体验分 4.6、PXI 70/60、大促退款率 5%、放量 ≤50% 等）来自知识库，"
                 "见 `compliance-medical` / `data-metrics` / `profit-model` / `campaign-playbook`。")

    tao.close()
    erp.close()
    return shop_name, lines, True


def main():
    ap = argparse.ArgumentParser(description="每日巡店 —— 读 PG 输出巡店报告")
    ap.add_argument("--shop", default="all",
                    help="店铺 schema 后缀（haoyale/feite/...）或 all")
    ap.add_argument("--date", help="统计日期 YYYY-MM-DD，默认取各表最新")
    ap.add_argument("--out", help="输出文件路径，默认打印到 stdout")
    args = ap.parse_args()

    want_date = date.fromisoformat(args.date) if args.date else None
    targets = SHOP_SCHEMA_SUFFIXES if args.shop == "all" else [args.shop]

    out = ["# 每日巡店报告", "",
           f"生成时间：{date.today()}　｜　店铺范围：{args.shop}", "",
           "> 数据源：本机 PostgreSQL 的 `taobao` 库（店铺侧）与 `erp` 库（交易/成本侧）。", ""]

    for sfx in targets:
        out.append("")
        out.append("=" * 72)
        try:
            name, lines, ok = report_shop(sfx, want_date)
            out.extend(lines)
            if not ok:
                out.extend(["", "> ⚠️ 该店数据不足，未生成巡店结论。"])
        except Exception as e:
            out.extend(["", f"> ❌ 处理 {sfx} 时出错：{type(e).__name__}: {e}"])
            if os.environ.get("PATROL_DEBUG"):
                import traceback
                out.extend(["```", traceback.format_exc(), "```"])
        out.append("")
        out.append("=" * 72)

    text = "\n".join(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()

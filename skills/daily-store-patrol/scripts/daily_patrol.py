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
                 "领先率代理指标；<50% 说明主要在跑收割（`store-diagnosis`） |")
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
        r = q(tcur, f'''select "用户数","未购买用户数","已购用户数","新访客户数","潜在客户数",
                                "已购客户回访数","180天复购率","总粉丝数","活跃粉丝数","沉睡粉丝数",
                                "机会粉丝数","成交新客占比","父订单数","复购父订单数"
                         from "{schema}"."customer_assets_2026" where stat_date=%s''', (d_target,))
        if r and r[0][0] != "__error__" and len(r[0]) > 1:
            v = r[0]
            rp = num(v[6])
            lines.append("| 指标 | 值 | 看什么 |")
            lines.append("|---|---|---|")
            for label, val_, note in (
                ("用户总数", v[0], "池子大小"),
                ("新访客户数", v[3], "拉新入口的量"),
                ("潜在客户数", v[4], "到过店但没成交的人"),
                ("已购客户数", v[2], "存量买家"),
                ("已购客户回访数", v[5], "回访有没有发生"),
                ("180天复购率", f"{fmt(rp*100)}%" if rp is not None else "—", "复购健康度"),
                ("总粉丝数", v[7], "私域池"),
                ("活跃粉丝", v[8], "触达得到"),
                ("沉睡粉丝", v[9], "召回对象"),
                ("机会粉丝", v[10], "可激活"),
                ("成交新客占比", f"{fmt(v[11])}%" if num(v[11]) is not None else "—", "与店铺新客占比互相印证"),
                ("复购父订单占比", f"{fmt(pct(v[13], v[12]))}%", "复购强度"),
            ):
                lines.append(f"| {label} | {fmt(val_)} | {note} |")
            lines.append("")
            lines.append("> 沉睡粉丝多 + 复购率低 = 今日排召回（`customer-asset-ops`）；"
                         "潜在客户多而成交少 = 承接或人群包问题。")
        else:
            lines.append(f"（{d_target} 无客户资产记录）")

    # ---------- 4. 推广计划体检 ----------
    hdr("## 4 · 推广计划体检")
    lines.append("| 推广类型 | 计划 | 花费 | 直接成交 | 间接成交 | 投产 | 新客数 | 判读 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    findings = []
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
                findings.append((kind, plan, cost, txt))
    lines.append("")
    lines.append(f"> 万相台数据最新日期：{', '.join(sorted({str(latest_date(tcur, schema, t)) for t in ('wxt_promotion_baobei_2026','wxt_promotion_keyword_2026','wxt_promotion_audience_2026') if table_exists(tcur, schema, t)}))}"
                 "（比店铺日报滞后约 3 周，**不能当成昨日数据用**）")
    lines.append("> 投产比此处用（直接+间接）成交 ÷ 花费近似；平台自带 `投入产出比` 字段口径可能不同，"
                 "最终以平台字段为准。")
    lines.append("> 判读红线（知识库）：**间接成交 = 直接成交 2 倍 ⇒ 该品投放完全无效**。")

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
        lines.append(f"| {label} | {fmt(cv)} | {fmt(bv)} | "
                     f"{'🟢 绿' if color=='绿' else '🟡 黄' if color=='黄' else '🔴 红'} |")
    lines.append("")
    lines.append("### 今日行动清单")
    lines.append("")
    actions = []
    for label, cv, bv, color, note, direction in lights:
        if color == "红":
            actions.append(f"🔴 **{label}** {fmt(cv)}（7日均值 {fmt(bv)}，{note}）→ 进专项诊断")
    for kind, plan, cost, txt in findings[:8]:
        actions.append(f"🔴 **推广计划 · {kind} · {plan}**（花费 {fmt(cost)}）→ {txt}")
    if not actions:
        actions.append("🟢 无红灯项：保持节奏，把精力转向机会项。")
    lines.extend(f"- {a}" for a in actions)
    lines.append("")
    lines.append("### 机会项提示")
    lines.append("")
    lines.append("- 费比低于 7 日均值且投产达标 → 回收预算、加投赢家（`wanxiangtai-wujie`）")
    lines.append("- 某二级流量来源转化率显著高于店铺均值 → 该来源加预算（`keyword-promo`）")
    lines.append("- 新客占比偏低 + 老客占比高 → 在跑收割，需开拉新计划（`customer-asset-ops`）")
    lines.append("- 沉睡粉丝多 + 复购率低 → 今日排召回（`customer-asset-ops`）")
    lines.append("- 复购率与老客金额占比双升 → 该品升 A 级承接（`sabc-product-tiering`）")
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推广红绿灯报表生成器 —— 从数据生成红绿灯报表，并基于历史数据反推推广目标。

两条数据通道（由数据现实决定，不是取舍）：

  A. 商品/系列级（Excel 通道）
     输入：生意参谋「商品明细」+ 万相台「商品报表」的导出表，列名与
     《推广红绿灯》模板一致（工作表：上月数据 / 本月数据 / 宝贝清单）。
     为什么必须走这条：商品级 GMV、访客、转化率、退款率在生产库里
     **没有对应字段** —— core_daily 是店铺级，erp 的 daily_sku_dd 的
     「商品编码」是 ERP 内部码（样例 `-YF`），与淘宝商品 ID 对不上。

  B. 店铺/计划级（PG 通道）
     输入：本机 PostgreSQL。taobao 库 shop_<店>.core_daily_2026（店铺经营
     日报）+ shop_<店>.wxt_promotion_{baobei,keyword,audience}_2026（万相台
     计划级花费与成交）+ erp 库 erp_result.daily_store_dd_2026（订单口径的
     销售/退货/成本/毛利率）。
     为什么只能到店铺级：商品级成交与访客在 PG 里没有，且万相台宝贝表的
     主体ID 是商品 ID、而成交侧无同粒度数据，join 不上。
     实测踩到的五个口径坑（都写在 pg_load_shop 的注释里）：
       ① 日期列是 stat_date；wxt 表里「日期」列整列 NULL。
       ② 万相台是**月度快照**（stat_date 每月只有 1 个值），只能按自然月取。
       ③ 万相台三张表是同一批计划的不同维度视图，相加会把花费算两倍
          （9 月实测：相加 670,818，真实 330,701）⇒ 按计划ID 去重。
       ④ core_daily 的「成功退款金额」是当天发生额，不是退款率；
          退款率要用 ERP 按订单日期的「退货金额」。
       ⑤ ERP 的「推广费用」一个月只有 1 天有值（月末快照），按天 sum 会错；
          推广花费用 core_daily 四项逐日相加。

口径（与《推广红绿灯》模板逐行反推核对一致）：
  GSV（净成交） = GMV − 退款金额
  退款率       = 退款金额 ÷ GMV
  客单价       = GMV ÷ 支付人数          ← 注意是 GMV 口径，不是 GSV
  转化率       = 支付人数 ÷ 访客数
  推广费比     = 推广花费 ÷ GMV          ← 毛口径
  去退推广费比 = 推广花费 ÷ GSV          ← 净口径
  投产比 ROI   = 推广成交金额 ÷ 推广花费  ← 分子含直接 + 间接成交
  推广成交占比 = 推广成交金额 ÷ GMV
  推广点击单价 = 推广花费 ÷ 推广点击量
  平均访客成本 = 推广花费 ÷ 访客数

目标制定（双轨，取严）：
  轨道 A · 利润约束（底线，来自 profit-model 的利润公式与盈亏平衡投产比）
      目标投产比下限 = 1 ÷ [毛利率 × (1 − 退款率)]     （实盘取更严的一版）
      目标去退费比上限 = (毛利率 − 运营成本率) ÷ (1 − 退款率)
  轨道 B · 历史基线（可达，来自《推广红绿灯》模板的预估目标链）
      目标 GSV（净） = 上期 GSV
      目标 GMV（毛） = 上期 GSV ÷ (1 − 上期退款率)
      目标投产比参考 = 上期实际投产比
      目标去退费比参考 = 上期实际去退推广费比
  取严：目标投产比 = max(A 下限, B 参考)；目标去退费比 = min(A 上限, B 参考)
  目标花费 = 目标 GSV（净）× 目标去退费比   ← 费比分母是 GSV，毛净不能混用
  目标流量 = 目标 GMV ÷ (基线客单价 × 基线转化率)
  目标推广成交金额 = 目标 GMV × 基线推广成交占比
  目标点击量 = 目标花费 ÷ 基线推广点击单价
  目标进度 = 目标值 ÷ 期初营业天数 × 已过天数（按天折算）

判定（两轴三色，阈值来自《基于人群资产的淘天运营方法4：多端数据融合调优》）：
  投产灯：绿 ≥ 目标投产比｜黄 ≥ 目标×0.8｜红 < 目标×0.8
  费比灯：绿 ≤ 目标去退费比｜黄 ≤ 目标×1.2｜红 > 目标×1.2
  总灯 = 两轴取更差的一盏（**脚本合成规则，原文按四场景分别决策，未定义单灯**）

用法：
    python red_green_report.py --input 推广红绿灯.xlsx --out-md 报表.md
    python red_green_report.py --input 推广红绿灯.xlsx --out-xlsx 红绿灯报表.xlsx
    python red_green_report.py --pg-shop all --out-md 店铺红绿灯.md
    python red_green_report.py --self-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Any

# ---------------------------------------------------------------- 口径常量

# 《推广红绿灯》模板与 aiec 课程原文写死的红绿灯阈值
ROI_YELLOW_FACTOR = 0.8      # 投产黄灯带：目标 × 0.8
FEE_YELLOW_FACTOR = 1.2      # 费比黄灯带：目标 × 1.2

GREEN, YELLOW, RED = "绿", "黄", "红"

# 场景 →（场景名, 预算动作, 依据）。
# aiec 原文只定义了四个场景（§3.2）与一条总原则（§4.1「绿灯加、红灯减、黄灯观望优化」，
# 「每次调整预算幅度不超过 30%」）、「连续 3 天黄灯立即调整」（§3.3）。
# 下面前六行里，四个原文场景原样保留；黄灯参与的组合按 §4.1 归入观望；
# 「红+黄」是**脚本合成规则** —— 原文四场景没覆盖这种混合档，
# 报告与技能章节里都显式标注，不假装是原文。
SCENE_ACTION = {
    (GREEN, GREEN): ("双绿", "加预算 20%-30%（系列总增幅 ≤30%）", "aiec §3.2 场景1 + §4.2"),
    (GREEN, RED): ("投产绿/费比红",
                   "查退款率＞30% 与间接成交占比＞50%；减 30%-50% 预算",
                   "aiec §3.2 场景2"),
    (RED, GREEN): ("投产红/费比绿",
                   "查免费流量占比＞70%、推广日预算＜500、拉新占比＞80%；必要时加收割预算",
                   "aiec §3.2 场景3"),
    (RED, RED): ("双红", "立即减预算 50%-80% 或暂停，优化后小预算重启", "aiec §3.2 场景4"),
    (GREEN, YELLOW): ("投产绿/费比黄",
                      "黄灯观望优化；连续 3 天黄灯再调整，单次幅度 ≤30%",
                      "aiec §4.1 + §3.3"),
    (YELLOW, GREEN): ("投产黄/费比绿",
                      "黄灯观望优化；连续 3 天黄灯再调整，单次幅度 ≤30%",
                      "aiec §4.1 + §3.3"),
    (YELLOW, YELLOW): ("双黄",
                       "黄灯观望优化；连续 3 天黄灯再调整，单次幅度 ≤30%",
                       "aiec §4.1 + §3.3"),
    (YELLOW, RED): ("投产黄/费比红",
                    "按费比红灯侧处置：查退款率＞30% 与间接成交占比＞50%；减 30%-50% 预算",
                    "aiec §3.2 场景2（费比红灯侧）"),
    (RED, YELLOW): ("⚠️ 混合档：投产红/费比黄",
                    "按投产红灯侧排查；预算单次调整 ≤30%，不直接套用双红的 50%-80%",
                    "脚本合成规则（原文四场景未覆盖）"),
}

# 模板里的商品ID 汇总行标签
AGG_IDS = {"(空白)", "合计", "总计", "汇总"}


# ---------------------------------------------------------------- 工具函数


def num(value: Any) -> float:
    """把表格里可能带逗号/空/文字的金额字段转成 float，取不到就 0。

    带百分号的文本按百分数解析（9.27% → 0.0927）；Excel 单元格存成
    数值 + 百分比格式时（0.0927）本来就直接是分数，不需要再换算。
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return 0.0
    if not text or text in {"-", "—", "nan", "None"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def product_id(value: Any) -> str:
    """商品 ID 可能是数字也可能被 Excel 存成文本，统一成无小数的字符串。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def pct(value: float, digits: int = 2) -> str:
    return f"{value * 100:.{digits}f}%"


def money(value: float) -> str:
    return f"{value:,.2f}"


def _ge(value: float, threshold: float) -> bool:
    """带容差的大于等于。

    边界不能因浮点误差掉档：3.0 × 0.8 在 IEEE754 下是 2.4000000000000004，
    拿「投产恰好等于目标×0.8」去比会得到 False 而掉进红灯 —— 但按原文
    黄灯带是「≥ 目标×0.8 且 < 目标」，这个值必须落在黄灯。
    """
    return value >= threshold - max(1e-9, abs(threshold) * 1e-12)


def _le(value: float, threshold: float) -> bool:
    """带容差的小于等于，理由同 _ge。"""
    return value <= threshold + max(1e-9, abs(threshold) * 1e-12)


def lamp_roi(roi: float, target: float) -> str:
    if target <= 0:
        return YELLOW
    if _ge(roi, target):
        return GREEN
    if _ge(roi, target * ROI_YELLOW_FACTOR):
        return YELLOW
    return RED


def lamp_fee(fee: float, target: float) -> str:
    if target <= 0:
        return YELLOW
    if _le(fee, target):
        return GREEN
    if _le(fee, target * FEE_YELLOW_FACTOR):
        return YELLOW
    return RED


def scene_of(roi_lamp: str, fee_lamp: str) -> str:
    """八种组合归类：四个 aiec 原文场景 + 黄灯组合（按 §4.1 观望）+ 红黄混合档（脚本规则）。"""
    return SCENE_ACTION.get((roi_lamp, fee_lamp), ("未知", "—", ""))[0]


def scene_action(roi_lamp: str, fee_lamp: str) -> tuple[str, str, str]:
    """返回（场景名, 预算动作, 依据）。"""
    return SCENE_ACTION.get((roi_lamp, fee_lamp), ("未知", "—", ""))


# ---------------------------------------------------------------- 记录模型


def build_record(item_id: str, name: str, group: str, stage: str,
                 gmv: float, refund: float, visitors: float, buyers: float,
                 clicks: float, cost: float, ad_gmv: float, indirect_gmv: float) -> dict:
    """按已核对的口径算出一个商品的全部指标。

    传入的是**原始量**，所有比率在这里现算，不读表里预存的比率列 ——
    否则一旦表里的比率列是旧口径，算出来的报表会跟着错。
    """
    gsv = gmv - refund
    ad_indirect = indirect_gmv
    ad_direct = ad_gmv - ad_indirect
    rec = {
        "id": item_id,
        "name": name,
        "group": group or "未分组",
        "stage": stage or "未标注",
        "gmv": gmv,
        "refund": refund,
        "gsv": gsv,
        "visitors": visitors,
        "buyers": buyers,
        "clicks": clicks,
        "cost": cost,
        "ad_gmv": ad_gmv,
        "ad_direct": ad_direct,
        "ad_indirect": ad_indirect,
    }
    rec["refund_rate"] = safe_div(refund, gmv)
    rec["aov"] = safe_div(gmv, buyers)
    rec["cvr"] = safe_div(buyers, visitors)
    rec["roi"] = safe_div(ad_gmv, cost)
    rec["fee_rate"] = safe_div(cost, gmv)          # 推广费比（毛口径）
    rec["fee_rate_net"] = safe_div(cost, gsv)      # 去退推广费比（净口径）
    rec["ad_share"] = safe_div(ad_gmv, gmv)
    rec["indirect_share"] = safe_div(ad_indirect, ad_gmv)
    rec["cpc"] = safe_div(cost, clicks)
    rec["cpa"] = safe_div(cost, visitors)
    return rec


def aggregate(records: list[dict]) -> dict:
    """把一组商品记录汇总成大盘。比率一律用汇总后的量重算，不平均比率。"""
    out: dict[str, Any] = {"n": len(records)}
    for key in ("gmv", "refund", "gsv", "visitors", "buyers", "clicks", "cost",
                "ad_gmv", "ad_direct", "ad_indirect"):
        out[key] = sum(r[key] for r in records)
    out["refund_rate"] = safe_div(out["refund"], out["gmv"])
    out["aov"] = safe_div(out["gmv"], out["buyers"])
    out["cvr"] = safe_div(out["buyers"], out["visitors"])
    out["roi"] = safe_div(out["ad_gmv"], out["cost"])
    out["fee_rate"] = safe_div(out["cost"], out["gmv"])
    out["fee_rate_net"] = safe_div(out["cost"], out["gsv"])
    out["ad_share"] = safe_div(out["ad_gmv"], out["gmv"])
    out["indirect_share"] = safe_div(out["ad_indirect"], out["ad_gmv"])
    out["cpc"] = safe_div(out["cost"], out["clicks"])
    out["cpa"] = safe_div(out["cost"], out["visitors"])
    return out


# ---------------------------------------------------------------- 目标制定


def derive_targets(base: dict, current: dict, gross_margin: float,
                   opex_rate: float, elapsed_days: float,
                   period_days: float) -> dict:
    """双轨目标：利润约束给底线，历史基线给可达，两者取严。

    利润约束的口径来自 profit-model 的「利润 = 销售额 × 毛利率 − 运营成本 −
    推广费用」与「盈亏平衡投产比 = 1 ÷ [毛利率 × (1 − 退款率)]」：
      目标投产比下限 = 1 ÷ [毛利率 × (1 − 当期退款率)]
      目标去退费比上限 = (毛利率 − 运营成本率) ÷ (1 − 当期退款率)
    历史基线的口径来自《推广红绿灯》模板的预估目标链：
      预估目标 GSV = 上期 GSV ÷ (1 − 上期退款率)
    """
    refund_rate = current["refund_rate"]
    be_roi = safe_div(1.0, gross_margin * (1 - refund_rate)) if gross_margin > 0 else 0.0
    max_fee_net = safe_div(gross_margin - opex_rate, 1 - refund_rate) if gross_margin > 0 else 0.0
    if max_fee_net < 0:
        max_fee_net = 0.0

    # 轨道 B · 历史基线
    base_roi = base["roi"]
    base_fee_net = base["fee_rate_net"]
    base_gsv = base["gsv"]
    base_refund_rate = base["refund_rate"]

    # 模板的目标链（《推广红绿灯》「预估目标」行）：
    #   目标GMV（毛）= 上期GSV ÷ (1 − 上期退款率)   ≡ 上期GMV
    #   目标GSV（净）= 上期GSV                      ← 守住上期净成交规模
    # ⚠️ 毛/净不能混用：推广费比分母是 GSV，所以「目标推广花费」必须用
    # **目标GSV（净）× 目标去退费比**；用毛 GMV 乘净费比会把目标花费高估。
    target_gmv = safe_div(base_gsv, 1 - base_refund_rate) if base_gsv else 0.0
    target_gsv = base_gsv
    # 更严变体：按**当期**退款率折算，退款率上升时要多卖才能守住同样的净成交
    target_gmv_at_cur_refund = safe_div(base_gsv, 1 - refund_rate) if base_gsv else 0.0

    # 取严
    target_roi = max(be_roi, base_roi)
    target_fee_net = min(max_fee_net, base_fee_net) if max_fee_net > 0 else base_fee_net
    if target_fee_net <= 0:
        target_fee_net = base_fee_net

    target_cost = target_gsv * target_fee_net
    target_visitors = safe_div(target_gmv, base["aov"] * base["cvr"]) if base["aov"] and base["cvr"] else 0.0
    target_clicks = safe_div(target_cost, base["cpc"]) if base["cpc"] else 0.0
    # 模板的 R6：目标推广成交金额 = 目标GMV（毛）× 上期推广成交占比
    target_ad_gmv = target_gmv * base["ad_share"]

    ratio = safe_div(elapsed_days, period_days) if period_days else 1.0
    return {
        "gross_margin": gross_margin,
        "opex_rate": opex_rate,
        "be_roi": be_roi,
        "max_fee_net": max_fee_net,
        "base_roi": base_roi,
        "base_fee_net": base_fee_net,
        "base_gsv": base_gsv,
        "base_refund_rate": base_refund_rate,
        "target_roi": target_roi,
        "target_fee_net": target_fee_net,
        "target_gsv": target_gsv,
        "target_gmv": target_gmv,
        "target_gmv_at_cur_refund": target_gmv_at_cur_refund,
        "target_cost": target_cost,
        "target_visitors": target_visitors,
        "target_clicks": target_clicks,
        "target_ad_gmv": target_ad_gmv,
        "elapsed_days": elapsed_days,
        "period_days": period_days,
        "progress_ratio": ratio,
        "target_gsv_to_date": target_gsv * ratio,
        "target_gmv_to_date": target_gmv * ratio,
        "target_cost_to_date": target_cost * ratio,
    }


def judge(current: dict, targets: dict) -> dict:
    """两轴三色 + 四场景 + 动作 + 完成度。"""
    roi_lamp = lamp_roi(current["roi"], targets["target_roi"])
    fee_lamp = lamp_fee(current["fee_rate_net"], targets["target_fee_net"])
    scene, action, basis = scene_action(roi_lamp, fee_lamp)
    completion_gsv = safe_div(current["gsv"], targets["target_gsv_to_date"])
    completion_gmv = safe_div(current["gmv"], targets["target_gmv_to_date"])
    completion_roi = safe_div(current["roi"], targets["target_roi"])
    completion_fee = safe_div(current["fee_rate_net"], targets["target_fee_net"])
    overall = RED if RED in (roi_lamp, fee_lamp) else (YELLOW if YELLOW in (roi_lamp, fee_lamp) else GREEN)
    return {
        "roi_lamp": roi_lamp,
        "fee_lamp": fee_lamp,
        "overall": overall,
        "scene": scene,
        "action": action,
        "basis": basis,
        "completion_gsv": completion_gsv,
        "completion_gmv": completion_gmv,
        "completion_roi": completion_roi,
        "completion_fee": completion_fee,
    }


# ---------------------------------------------------------------- Excel 通道


def read_sheet_rows(worksheet) -> list[dict]:
    """把一张表读成 list[dict]，第一行是表头。"""
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for raw in rows[1:]:
        if all(v is None or str(v).strip() == "" for v in raw):
            continue
        out.append({header[i]: (raw[i] if i < len(raw) else None) for i in range(len(header))})
    return out


def pick_column(rows: list[dict], *candidates: str) -> str | None:
    """按候选名找列（容忍前后空白与「上月/本月」前缀差异）。"""
    if not rows:
        return None
    keys = list(rows[0].keys())
    for cand in candidates:
        for key in keys:
            if key.strip() == cand:
                return key
    for cand in candidates:
        for key in keys:
            if cand in key:
                return key
    return None


def load_excel_channel(path: str) -> dict:
    """读《推广红绿灯》模板（或同结构导出表）。"""
    try:
        import openpyxl
    except ImportError:
        sys.exit("需要 openpyxl：pip install openpyxl")

    try:
        book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except FileNotFoundError:
        sys.exit(f"找不到输入文件：{path}")
    except Exception as exc:
        sys.exit(f"读取输入文件失败：{path}（{exc}）")
    names = book.sheetnames

    def find_sheet(*cands: str) -> str | None:
        for cand in cands:
            for name in names:
                if cand in name:
                    return name
        return None

    prev_sheet = find_sheet("上月数据")
    curr_sheet = find_sheet("本月数据")
    attr_sheet = find_sheet("宝贝清单")
    if not curr_sheet:
        sys.exit(f"找不到「本月数据」工作表，现有工作表：{names}")

    curr_rows = read_sheet_rows(book[curr_sheet])
    prev_rows = read_sheet_rows(book[prev_sheet]) if prev_sheet else []
    attr_rows = read_sheet_rows(book[attr_sheet]) if attr_sheet else []

    c_id = pick_column(curr_rows, "商品ID")
    c_gmv = pick_column(curr_rows, "GMV")
    c_refund = pick_column(curr_rows, "退款金额")
    c_uv = pick_column(curr_rows, "访客数")
    c_buyers = pick_column(curr_rows, "支付人数")
    c_clicks = pick_column(curr_rows, "推广点击量")
    c_cost = pick_column(curr_rows, "推广花费")
    c_adgmv = pick_column(curr_rows, "推广成交金额")
    c_ind = pick_column(curr_rows, "间接成交占比")

    p_id = pick_column(prev_rows, "商品ID")
    p_gmv = pick_column(prev_rows, "上月GMV")
    p_refund = pick_column(prev_rows, "上月退款金额")
    p_uv = pick_column(prev_rows, "上月访客数")
    p_buyers = pick_column(prev_rows, "上月支付人数")
    p_clicks = pick_column(prev_rows, "上月推广点击量")
    p_cost = pick_column(prev_rows, "上月推广花费")
    p_adgmv = pick_column(prev_rows, "上月推广成交金额")
    p_ind = pick_column(prev_rows, "上月间接成交占比")

    a_id = pick_column(attr_rows, "商品ID")
    a_group = pick_column(attr_rows, "品类名称")
    a_stage = pick_column(attr_rows, "货品成长阶段")
    a_name = pick_column(attr_rows, "宝贝名称")
    a_price = pick_column(attr_rows, "价格带层级")

    attrs: dict[str, dict] = {}
    for row in attr_rows:
        key = product_id(row.get(a_id)) if a_id else ""
        if key:
            attrs[key] = {
                "name": str(row.get(a_name) or "").strip() if a_name else "",
                "group": str(row.get(a_group) or "").strip() if a_group else "",
                "stage": str(row.get(a_stage) or "").strip() if a_stage else "",
                "price": str(row.get(a_price) or "").strip() if a_price else "",
            }

    def row_metrics(row, gmv_col, refund_col, uv_col, buyers_col,
                    clicks_col, cost_col, adgmv_col, ind_col) -> dict:
        """从一行里取出原始量（比率一律现算，不取表里的比率列）。"""
        gmv = num(row.get(gmv_col)) if gmv_col else 0.0
        refund = num(row.get(refund_col)) if refund_col else 0.0
        ad_gmv = num(row.get(adgmv_col)) if adgmv_col else 0.0
        # 间接成交金额：表里只给「间接成交占比」，乘回推广成交金额还原
        ind_share = num(row.get(ind_col)) if ind_col else 0.0
        return {
            "gmv": gmv, "refund": refund, "ad_gmv": ad_gmv,
            "visitors": num(row.get(uv_col)) if uv_col else 0.0,
            "buyers": num(row.get(buyers_col)) if buyers_col else 0.0,
            "clicks": num(row.get(clicks_col)) if clicks_col else 0.0,
            "cost": num(row.get(cost_col)) if cost_col else 0.0,
            "indirect_gmv": ad_gmv * ind_share,
        }

    def split(rows, id_col) -> tuple[list[dict], list[tuple[str, dict]]]:
        """拆成明细行与汇总行。模板的汇总行标签有 (空白)/合计/总计 三种。"""
        items: list[dict] = []
        aggs: list[tuple[str, dict]] = []
        for row in rows:
            key = product_id(row.get(id_col)) if id_col else ""
            if key in AGG_IDS:
                aggs.append((key, row))
            elif key:
                items.append(row)
        return items, aggs

    def make(rows, id_col, gmv_col, refund_col, uv_col, buyers_col,
             clicks_col, cost_col, adgmv_col, ind_col) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in rows:
            key = product_id(row.get(id_col)) if id_col else ""
            if not key or key in AGG_IDS:
                continue
            m = row_metrics(row, gmv_col, refund_col, uv_col, buyers_col,
                            clicks_col, cost_col, adgmv_col, ind_col)
            out[key] = build_record(
                item_id=key,
                name=attrs.get(key, {}).get("name", ""),
                group=attrs.get(key, {}).get("group", ""),
                stage=attrs.get(key, {}).get("stage", ""),
                gmv=m["gmv"], refund=m["refund"],
                visitors=m["visitors"], buyers=m["buyers"], clicks=m["clicks"],
                cost=m["cost"], ad_gmv=m["ad_gmv"], indirect_gmv=m["indirect_gmv"],
            )
        return out

    def classify_aggs(aggs) -> tuple[tuple[str, dict] | None, list[dict], tuple[str, dict] | None]:
        """把汇总行分成三类：顶部大盘行、差额行、总计行。

        真实模板的结构（已逐列验证）：明细区**第一个**汇总行是大盘，
        明细区中间还藏着一条标签同为「(空白)」的差额行，
        末尾的「总计」行与大盘行数值相等。
        ⇒ 大盘 ≠ 明细逐行相加，差额恰好等于那条差额行。
        """
        if not aggs:
            return None, [], None
        store = aggs[0]
        diffs: list[dict] = []
        total = None
        for key, row in aggs[1:]:
            if key == "总计":
                total = (key, row)
            else:
                diffs.append(row)
        return store, diffs, total

    def store_record(row, label, gmv_col, refund_col, uv_col, buyers_col,
                     clicks_col, cost_col, adgmv_col, ind_col) -> dict:
        m = row_metrics(row, gmv_col, refund_col, uv_col, buyers_col,
                        clicks_col, cost_col, adgmv_col, ind_col)
        return build_record(item_id="__大盘__", name=label, group="大盘", stage="大盘",
                            gmv=m["gmv"], refund=m["refund"], visitors=m["visitors"],
                            buyers=m["buyers"], clicks=m["clicks"], cost=m["cost"],
                            ad_gmv=m["ad_gmv"], indirect_gmv=m["indirect_gmv"])

    RAW_KEYS = ("gmv", "refund", "visitors", "buyers", "clicks", "cost", "ad_gmv")

    def reconcile(store_rec, item_agg, other_recs) -> dict:
        """大盘行 − 明细合计 的差额，以及其余汇总行能否解释这个差额。"""
        out: dict[str, dict] = {}
        for key in RAW_KEYS:
            diff = store_rec[key] - item_agg[key]
            other = sum(r[key] for r in other_recs)
            out[key] = {"diff": diff, "other_rows": other,
                        "matched": abs(diff - other) < 0.005}
        return out

    cur_items, cur_aggs = split(curr_rows, c_id)
    prev_items, prev_aggs = split(prev_rows, p_id)

    current = make(cur_items, c_id, c_gmv, c_refund, c_uv, c_buyers,
                   c_clicks, c_cost, c_adgmv, c_ind)
    base = make(prev_items, p_id, p_gmv, p_refund, p_uv, p_buyers,
                p_clicks, p_cost, p_adgmv, p_ind)

    # 大盘：取模板自己的汇总行，不用明细相加
    cur_store, cur_diffs, cur_total = classify_aggs(cur_aggs)
    prev_store, prev_diffs, prev_total = classify_aggs(prev_aggs)
    store_current = store_record(cur_store[1], "本月大盘", c_gmv, c_refund, c_uv,
                                  c_buyers, c_clicks, c_cost, c_adgmv, c_ind) if cur_store else None
    store_base = store_record(prev_store[1], "上月大盘", p_gmv, p_refund, p_uv,
                               p_buyers, p_clicks, p_cost, p_adgmv, p_ind) if prev_store else None

    # 其余汇总行（模板在明细区中间插的差额行）
    cur_other = [store_record(row, "差额行", c_gmv, c_refund, c_uv, c_buyers,
                               c_clicks, c_cost, c_adgmv, c_ind) for row in cur_diffs]
    prev_other = [store_record(row, "差额行", p_gmv, p_refund, p_uv, p_buyers,
                               p_clicks, p_cost, p_adgmv, p_ind) for row in prev_diffs]

    item_agg_current = aggregate(list(current.values()))
    item_agg_base = aggregate(list(base.values())) if base else item_agg_current
    recon_current = reconcile(store_current, item_agg_current, cur_other) if store_current else {}
    recon_base = reconcile(store_base, item_agg_base, prev_other) if store_base else {}

    # 交叉校验：大盘行与「总计」行是否一致
    total_check = {}
    for label, store_rec, total_pair, cols in (
            ("本月", store_current, cur_total, (c_gmv, c_refund, c_uv, c_buyers,
                                                c_clicks, c_cost, c_adgmv, c_ind)),
            ("上月", store_base, prev_total, (p_gmv, p_refund, p_uv, p_buyers,
                                              p_clicks, p_cost, p_adgmv, p_ind))):
        if not (store_rec and total_pair):
            continue
        total_rec = store_record(total_pair[1], "总计行", *cols)
        diffs = {k: round(store_rec[k] - total_rec[k], 6)
                 for k in ("gmv", "visitors", "buyers", "cost", "ad_gmv")}
        total_check[label] = {"consistent": all(abs(v) < 0.005 for v in diffs.values()),
                              "diffs": diffs}

    book.close()
    return {
        "current": current, "base": base, "attrs": attrs,
        "store_current": store_current, "store_base": store_base,
        "item_agg_current": item_agg_current, "item_agg_base": item_agg_base,
        "recon_current": recon_current, "recon_base": recon_base,
        "total_check": total_check,
        "n_agg_current": len(cur_aggs), "n_agg_base": len(prev_aggs),
    }


# ---------------------------------------------------------------- PG 通道


def pg_connect(dbname: str):
    """连本机 PostgreSQL。口令走 .pgpass / PGPASSWORD，脚本不内置任何账号口令。

    libpq 只在 pgpass 条目的库名匹配时才给口令，而本机 pgpass 里既有
    `库=jst_dw` 的专属条目也有 `库=*` 的通配条目 —— 所以这里自己解析
    pgpass，挑出库名匹配（优先精确、其次通配）的那一条。
    """
    try:
        import psycopg2
    except ImportError:
        sys.exit("需要 psycopg2：pip install psycopg2-binary")

    host = os.environ.get("PGHOST", "127.0.0.1")
    port = int(os.environ.get("PGPORT", "5432"))
    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "")

    passfile = os.environ.get("PGPASSFILE")
    if not passfile:
        appdata = os.environ.get("APPDATA")
        candidate = os.path.join(appdata, "postgresql", "pgpass.conf") if appdata else ""
        passfile = candidate if candidate and os.path.exists(candidate) else None
    if not password and passfile and os.path.exists(passfile):
        exact, wildcard = None, None
        with open(passfile, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) < 5:
                    continue
                if parts[2] == dbname:
                    exact = parts
                    break
                if parts[2] == "*" and wildcard is None:
                    wildcard = parts
        chosen = exact or wildcard
        if chosen:
            host = chosen[0] or host
            port = int(chosen[1] or port)
            user = chosen[3] or user
            password = chosen[4]

    return psycopg2.connect(host=host, port=port, user=user, password=password,
                            dbname=dbname, connect_timeout=15)


SHOP_SCHEMA_SUFFIXES = [
    "haoyale", "feite", "fengshangzhi", "renhe", "zhuoguang", "jiantai", "darong",
]

# ERP 里的店铺名带平台后缀，与 taobao 库的 schema 后缀不是同名，
# 这里显式映射 —— 靠字符串猜会把「仁禾-天猫」和「仁禾-JD」搞混。
ERP_SHOP_NAMES = {
    "haoyale": "好雅乐医疗器械专营店",
    "feite": "飞特医疗器械专营店",
    "fengshangzhi": "风尚志旗舰店-天猫",
    "renhe": "仁禾医疗器械专营店-天猫",
    "zhuoguang": "卓广康健医疗器械专营店",
    "jiantai": "健泰医疗器械专营店",
    "darong": "大融医疗器械专营店",
}

WXT_TABLES = (("wxt_promotion_baobei_2026", "宝贝/货品"),
               ("wxt_promotion_keyword_2026", "关键词"),
               ("wxt_promotion_audience_2026", "人群"))


def pg_load_shop(shop: str, begin: dt.date, end: dt.date) -> dict:
    """取一个店的店铺级经营 + 计划级推广 + ERP 订单口径。

    ⚠️ 三处口径坑（都是实测踩出来的）：
      1. 日期列是 **stat_date**，不是「日期」—— wxt 表里「日期」列整列是 NULL，
         按它过滤会静默返回 0 行。
      2. core_daily 的「成功退款金额」是**当天发生的退款**（含历史订单退款），
         拿它除支付金额得到的不是退款率。真实退款率要用 ERP 按**订单日期**的「退货金额」。
      3. ERP 的「推广费用」一个月里只有 1 天有值（月末快照），
         按天 sum 会错；推广花费要用 core_daily 的四项逐日相加。
    """
    schema = f"shop_{shop}"
    out: dict[str, Any] = {"shop": shop, "begin": begin, "end": end}

    conn = pg_connect("taobao")
    cur = conn.cursor()

    # 店铺级经营：core_daily 是店铺级日报，取区间内逐日再汇总
    sql_shop = """
        select "stat_date", "访客数", "支付金额", "支付买家数", "支付转化率", "客单价",
               "成功退款金额", "支付新买家数", "支付老买家数", "新访客数",
               "全站推广花费", "关键词推广花费", "精准人群推广花费", "智能场景花费"
        from "{schema}"."core_daily_2026"
        where "stat_date" between %s and %s
        order by "stat_date"
    """
    cur.execute(sql_shop.format(schema=schema), (begin, end))
    days = cur.fetchall()
    if not days:
        conn.close()
        return {"error": f"{schema}.core_daily_2026 在 {begin}~{end} 没有数据"}

    total = {k: 0.0 for k in ("visitors", "gmv", "buyers", "refund", "new_buyers",
                               "old_buyers", "new_visitors", "cost")}
    for row in days:
        total["visitors"] += num(row[1])
        total["gmv"] += num(row[2])
        total["buyers"] += num(row[3])
        total["refund"] += num(row[6])
        total["new_buyers"] += num(row[7])
        total["old_buyers"] += num(row[8])
        total["new_visitors"] += num(row[9])
        total["cost"] += num(row[10]) + num(row[11]) + num(row[12]) + num(row[13])
    out["shop_level"] = {
        "days": len(days),
        "visitors": total["visitors"],
        "gmv": total["gmv"],
        "buyers": total["buyers"],
        "refund_cash": total["refund"],
        "new_buyers": total["new_buyers"],
        "old_buyers": total["old_buyers"],
        "new_visitors": total["new_visitors"],
        "cost": total["cost"],
    }

    # 计划级推广：万相台三张表（宝贝/关键词/人群）
    #
    # ⚠️ 两个必须知道的结构事实（都是实测出来的）：
    #  1. 万相台是**月度快照表** —— stat_date 每月只有一个值（实测都是当月 1 号）。
    #     按任意日期区间过滤会**静默返回 0 行**，所以只能按自然月取。
    #  2. 三张表是**同一批计划的不同维度视图**，不是三笔独立花费
    #     （实测：关键词表 20 个计划全部在宝贝表里，人群表 41 个里 39 个重叠）。
    #     三表相加 = 670,818，而真实花费 = 330,701（宝贝表口径）—— 直接相加会算两倍。
    #     ⇒ 店铺级汇总按**计划ID 去重后合并**。
    month_lo = dt.date(begin.year, begin.month, 1)
    month_hi = dt.date(end.year, end.month, 1)
    plans: list[dict] = []
    per_table: dict[str, list[dict]] = {}
    by_pid: dict[str, dict] = {}
    baobei_total = {"cost": 0.0, "direct": 0.0, "indirect": 0.0}
    for table, kind in WXT_TABLES:
        sql = f"""
            select "计划ID", "计划名字", sum("花费"), sum("直接成交金额"), sum("间接成交金额"),
                   sum("成交新客数"), sum("展现量"), sum("点击量")
            from "{schema}"."{table}"
            where "stat_date" between %s and %s
            group by 1, 2
        """
        try:
            cur.execute(sql, (month_lo, month_hi))
            rows = cur.fetchall()
        except Exception as exc:  # 表不存在或列名变了 —— 明确报出来，不静默跳过
            out.setdefault("promo_errors", []).append(f"{table}：{str(exc)[:120]}")
            per_table[kind] = []
            continue
        items: list[dict] = []
        per_pid: dict[str, dict] = {}
        for pid, pname, cost, direct, indirect, newcust, imp, clk in rows:
            key = str(pid)
            rec = {"cost": num(cost), "direct": num(direct), "indirect": num(indirect),
                   "newcust": num(newcust), "imp": num(imp), "clk": num(clk)}
            acc = per_pid.get(key)
            if acc is None:
                acc = dict(rec)
                acc["name"] = pname
                acc["_max"] = rec["cost"]
                per_pid[key] = acc
            else:
                # 同一计划ID 在同一张表里可能有多行（计划名字不同），先在表内求和
                for field in ("cost", "direct", "indirect", "newcust", "imp", "clk"):
                    acc[field] += rec[field]
                if rec["cost"] > acc["_max"]:
                    acc["name"] = pname
                    acc["_max"] = rec["cost"]
        for key, acc in per_pid.items():
            rec = {"kind": kind, "plan": acc["name"], "pid": key,
                   "cost": acc["cost"], "direct": acc["direct"], "indirect": acc["indirect"],
                   "newcust": acc["newcust"], "imp": acc["imp"], "clk": acc["clk"]}
            items.append(rec)
            prev = by_pid.get(key)
            if prev is None or rec["cost"] > prev["cost"]:
                by_pid[key] = rec
        per_table[kind] = sorted(items, key=lambda r: -r["cost"])
        if kind == "宝贝/货品":
            baobei_total["cost"] = sum(r["cost"] for r in items)
            baobei_total["direct"] = sum(r["direct"] for r in items)
            baobei_total["indirect"] = sum(r["indirect"] for r in items)
    # 计划体检清单：按类型分组，每类取花费前 20
    for kind, items in per_table.items():
        for rec in items[:20]:
            plans.append(rec)
    promo = {
        "cost": sum(r["cost"] for r in by_pid.values()),
        "direct": sum(r["direct"] for r in by_pid.values()),
        "indirect": sum(r["indirect"] for r in by_pid.values()),
        "newcust": sum(r["newcust"] for r in by_pid.values()),
        "imp": sum(r["imp"] for r in by_pid.values()),
        "clicks": sum(r["clk"] for r in by_pid.values()),
        "plans": len(by_pid),
        "month_lo": month_lo, "month_hi": month_hi,
        "baobei_cost": baobei_total["cost"],
    }
    conn.close()
    out["plans"] = plans
    out["promo_total"] = promo

    # ERP 订单口径：销售金额 / 退货金额 / 商家实收 / 实发成本 → 毛利率
    # ⚠️ 必须按「店铺名 + 类型='真实'」过滤，否则会把 JD/PDD 店铺和补单一起算进来；
    # ⚠️ 「推广费用」一个月只有 1 天有值（月末快照），只作对账参考，不参与费比。
    erp_name = ERP_SHOP_NAMES.get(shop)
    erp_level = {"days": 0, "sales": 0.0, "returns": 0.0, "gross_receipt": 0.0,
                 "cogs": 0.0, "promo_snapshot": 0.0, "promo_snapshot_rows": 0}
    gross_margin = 0.0
    if erp_name:
        try:
            ec = pg_connect("erp")
            ecur = ec.cursor()
            ecur.execute("""
                select count(*), sum("销售金额"), sum("退货金额"), sum("商家实收"),
                       sum("实发成本"), sum("推广费用"),
                       count(*) filter (where "推广费用" is not null)
                from erp_result.daily_store_dd_2026
                where "订单日期" between %s and %s and "店铺"=%s and "类型"='真实'
            """, (begin, end, erp_name))
            row = ecur.fetchone()
            ec.close()
            if row and num(row[3]) > 0:
                erp_level = {
                    "days": int(row[0] or 0), "sales": num(row[1]), "returns": num(row[2]),
                    "gross_receipt": num(row[3]), "cogs": num(row[4]),
                    "promo_snapshot": num(row[5]), "promo_snapshot_rows": int(row[6] or 0),
                }
                gross_margin = ((erp_level["gross_receipt"] - erp_level["cogs"])
                                / erp_level["gross_receipt"])
        except Exception as exc:
            out["erp_error"] = str(exc)[:160]
    out["erp_level"] = erp_level
    out["erp_shop_name"] = erp_name
    out["gross_margin"] = gross_margin
    return out


def plan_findings(plan: dict) -> list[str]:
    """计划级判读规则：沿用每日巡店脚本已实测的判据。"""
    verdict = []
    cost = plan["cost"]
    direct = plan["direct"]
    indirect = plan["indirect"]
    if cost > 0:
        if direct == 0:
            verdict.append("🔴 有花费无直接成交")
        elif indirect / direct >= 2:
            verdict.append("🔴 间接≥2倍直接=投放无效")
        roi = (direct + indirect) / cost
        if roi < 1:
            verdict.append("🔴 投产<1")
        elif roi >= 1.5 and plan["newcust"] == 0:
            verdict.append("🟡 只收割不拉新")
        elif roi >= 3 and plan["newcust"] > 0:
            verdict.append("🟢 投产达标且带新客")
    if plan["imp"] and plan["clk"]:
        ctr = plan["clk"] / plan["imp"]
        if ctr < 0.01:
            verdict.append("🟡 点击率<1%")
    return verdict


# ---------------------------------------------------------------- 报表输出


def render_markdown(levels: list[dict], targets: dict, current: dict, base: dict,
                    groups: dict[str, dict], stages: dict[str, dict],
                    items: list[dict], title: str, source_note: str,
                    recon_lines: list[str] | None = None,
                    item_agg: dict | None = None) -> str:
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(source_note)
    lines.append("")
    lines.append("## 一、目标（双轨取严）")
    lines.append("")
    lines.append("| 轨道 | 项目 | 数值 |")
    lines.append("|---|---|---|")
    lines.append(f"| A 利润约束 | 目标投产比下限（1÷[毛利率×(1−退款率)]） | {targets['be_roi']:.3f} |")
    lines.append(f"| A 利润约束 | 目标去退费比上限 | {pct(targets['max_fee_net'])} |")
    lines.append(f"| B 历史基线 | 上期实际投产比 | {targets['base_roi']:.3f} |")
    lines.append(f"| B 历史基线 | 上期实际去退费比 | {pct(targets['base_fee_net'])} |")
    lines.append(f"| **取严** | **目标投产比** | **{targets['target_roi']:.3f}** |")
    lines.append(f"| **取严** | **目标去退费比** | **{pct(targets['target_fee_net'])}** |")
    lines.append(f"| B 历史基线 | 目标 GSV（净）= 上期 GSV | {money(targets['target_gsv'])} |")
    lines.append(f"| B 历史基线 | 目标 GMV（毛）= 上期GSV÷(1−上期退款率) | {money(targets['target_gmv'])} |")
    lines.append(f"| 更严变体 | 目标 GMV（按当期退款率折算） | {money(targets['target_gmv_at_cur_refund'])} |")
    lines.append(f"| 推导 | 目标推广花费（目标GSV×目标去退费比） | {money(targets['target_cost'])} |")
    lines.append(f"| 推导 | 目标推广成交金额（目标GMV×上期推广成交占比） | {money(targets['target_ad_gmv'])} |")
    lines.append(f"| 推导 | 目标流量（目标GMV÷上期客单价÷上期转化率） | {targets['target_visitors']:,.0f} |")
    lines.append(f"| 推导 | 目标推广点击量（目标花费÷上期点击单价） | {targets['target_clicks']:,.0f} |")
    lines.append("")
    lines.append(f"> 毛利率 {pct(targets['gross_margin'])}｜运营成本率 {pct(targets['opex_rate'])}"
                 f"｜已过 {targets['elapsed_days']:.0f}/{targets['period_days']:.0f} 天"
                 f"（进度系数 {targets['progress_ratio']:.3f}）")
    lines.append("")

    lines.append("## 二、大盘红绿灯")
    lines.append("")
    lines.append("| 指标 | 目标 | 实际 | 差值 | 完成度 | 灯 |")
    lines.append("|---|---|---|---|---|---|")
    j = judge(current, targets)
    rows = [
        ("投产比 ROI", f"{targets['target_roi']:.3f}", f"{current['roi']:.3f}",
         f"{current['roi'] - targets['target_roi']:+.3f}", j["completion_roi"], j["roi_lamp"]),
        ("去退推广费比", pct(targets["target_fee_net"]), pct(current["fee_rate_net"]),
         f"{(current['fee_rate_net'] - targets['target_fee_net']) * 100:+.2f}pp",
         j["completion_fee"], j["fee_lamp"]),
        ("GMV（毛·模板口径）", money(targets["target_gmv_to_date"]), money(current["gmv"]),
         money(current["gmv"] - targets["target_gmv_to_date"]), j["completion_gmv"], "—"),
        ("GSV（净）", money(targets["target_gsv_to_date"]), money(current["gsv"]),
         money(current["gsv"] - targets["target_gsv_to_date"]), j["completion_gsv"], "—"),
    ]
    for name, tgt, act, diff, comp, lamp in rows:
        lines.append(f"| {name} | {tgt} | {act} | {diff} | {pct(comp)} | {lamp} |")
    lines.append("")
    lines.append(f"**总灯：{j['overall']}｜场景：{j['scene']}｜动作：{j['action']}**")
    lines.append("")
    lines.append(f"> 上期基线：GSV {money(base['gsv'])}｜投产比 {base['roi']:.3f}"
                 f"｜去退费比 {pct(base['fee_rate_net'])}｜退款率 {pct(base['refund_rate'])}")
    lines.append("")

    if recon_lines:
        lines.append("## 三、口径对账（大盘行 vs 明细合计）")
        lines.append("")
        lines.append("模板的明细区里还藏着汇总行，**大盘行 ≠ 明细逐行相加**。"
                     "本报告的大盘与目标基线一律取模板自己的大盘行，"
                     "下面列出两者差额与差额来源：")
        lines.append("")
        lines.append("| 指标 | 模板大盘行 | 明细合计 | 差额 | 差额行能否对上 |")
        lines.append("|---|---|---|---|---|")
        lines.extend(recon_lines)
        lines.append("")
        lines.append("> 「差额行能否对上」= 模板明细区里其余汇总行的合计是否等于该差额。"
                     "对得上说明明细与大盘的归属是完整的；对不上说明取数或导出有遗漏。")
        lines.append("")

    lines.append("## 四、分组红绿灯")
    lines.append("")
    if set(groups.keys()) == {"未分组"}:
        lines.append("> ⚠️ 「宝贝清单」的**品类名称**和**价格带层级**这两列没有填，"
                     "所以按系列/品类的分组全部落在「未分组」。"
                     "模板的「系列汇总-红绿灯」页也按 `类目[品类名称]` 取数，"
                     "不填这一列那一页全是 0 —— 要启用系列维度，先把这两列补齐。")
        lines.append("")
    if set(stages.keys()) == {"未标注"}:
        lines.append("> ⚠️ 「宝贝清单」的**货品成长阶段**也是空的，"
                     "本期无法按冷启/成长/平销/爆品分组。")
        lines.append("")
    for label, bucket in (("按系列/品类", groups), ("按货品成长阶段", stages)):
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| 分组 | 商品数 | GSV | 投产比 | 去退费比 | 投产灯 | 费比灯 | 总灯 | 动作 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for name, agg in sorted(bucket.items(), key=lambda kv: -kv[1]["gsv"]):
            sub = judge(agg, targets)
            lines.append(
                f"| {name} | {agg['n']} | {money(agg['gsv'])} | {agg['roi']:.3f} | "
                f"{pct(agg['fee_rate_net'])} | {sub['roi_lamp']} | {sub['fee_lamp']} | "
                f"{sub['overall']} | {sub['action']} |")
        lines.append("")

    lines.append("## 五、单品明细（按总灯与费比排序）")
    lines.append("")
    lines.append("| 商品ID | 名称 | 分组 | 阶段 | GSV | 投产比 | 去退费比 | 投产灯 | 费比灯 | 总灯 | 动作 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    order = {RED: 0, YELLOW: 1, GREEN: 2}
    ranked = sorted(items, key=lambda r: (order[r["judge"]["overall"]],
                                          -r["current"]["fee_rate_net"]))
    for row in ranked:
        cur = row["current"]
        jj = row["judge"]
        lines.append(
            f"| {row['id']} | {row['name'] or '—'} | {row['group']} | {row['stage']} | "
            f"{money(cur['gsv'])} | {cur['roi']:.3f} | {pct(cur['fee_rate_net'])} | "
            f"{jj['roi_lamp']} | {jj['fee_lamp']} | {jj['overall']} | {jj['action']} |")
    lines.append("")
    return "\n".join(lines)


def write_csv(path: str, items: list[dict]) -> None:
    import csv
    header = ["商品ID", "名称", "分组", "阶段", "GMV", "退款金额", "GSV", "退款率",
              "访客数", "支付人数", "转化率", "客单价", "推广花费", "推广点击量",
              "推广点击单价", "推广成交金额", "间接成交占比", "投产比", "推广费比",
              "去退推广费比", "投产灯", "费比灯", "总灯", "场景", "动作"]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in items:
            cur, jj = row["current"], row["judge"]
            writer.writerow([
                row["id"], row["name"], row["group"], row["stage"],
                f"{cur['gmv']:.2f}", f"{cur['refund']:.2f}", f"{cur['gsv']:.2f}",
                f"{cur['refund_rate']:.6f}", f"{cur['visitors']:.0f}", f"{cur['buyers']:.0f}",
                f"{cur['cvr']:.6f}", f"{cur['aov']:.4f}", f"{cur['cost']:.2f}",
                f"{cur['clicks']:.0f}", f"{cur['cpc']:.4f}", f"{cur['ad_gmv']:.2f}",
                f"{cur['indirect_share']:.6f}", f"{cur['roi']:.6f}",
                f"{cur['fee_rate']:.6f}", f"{cur['fee_rate_net']:.6f}",
                jj["roi_lamp"], jj["fee_lamp"], jj["overall"], jj["scene"], jj["action"],
            ])


def write_excel_report(path: str, items: list[dict], targets: dict, current: dict,
                        base: dict, groups: dict[str, dict], title: str) -> None:
    """输出**活公式**报表：改「目标假设」页的蓝字输入，全表重算。

    按 xlsx 技能的 formula-first 规范：黑色字是公式与计算结果，蓝色字是
    可改的输入（Assumptions），跨页引用用绿色字。
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        sys.exit("需要 openpyxl：pip install openpyxl")

    BLACK = Font(color="000000")
    BLUE = Font(color="0000FF")
    GREEN = Font(color="008000")
    HEADER = Font(bold=True, color="FFFFFF")
    HEADER_FILL = PatternFill("solid", fgColor="2F6F5E")
    YELLOW_FILL = PatternFill("solid", fgColor="FFFF00")

    book = Workbook()
    assump = book.active
    assump.title = "目标假设"

    assump["A1"] = "推广红绿灯 · 目标假设（蓝字可改，改完全表重算）"
    assump["A1"].font = Font(bold=True, size=13)
    rows = [
        ("毛利率", targets["gross_margin"], "来自 ERP 商家实收与实发成本"),
        ("运营成本率", targets["opex_rate"], "人工/仓储物流/平台扣点/退款退货/办公杂费 ÷ 销售额"),
        ("当期退款率", current["refund_rate"], "退款金额 ÷ GMV（数据实算）"),
        ("上期投产比", targets["base_roi"], "上期推广成交金额 ÷ 上期推广花费"),
        ("上期去退推广费比", targets["base_fee_net"], "上期推广花费 ÷ 上期GSV"),
        ("上期GSV", targets["base_gsv"], "上期GMV − 上期退款金额"),
        ("上期退款率", targets["base_refund_rate"], "上期退款金额 ÷ 上期GMV"),
        ("期初营业天数", targets["period_days"], "目标周期总天数"),
        ("已过天数", targets["elapsed_days"], "按天折算目标进度"),
    ]
    assump["A3"] = "参数"
    assump["B3"] = "取值"
    assump["C3"] = "说明"
    for col in ("A3", "B3", "C3"):
        assump[col].font = HEADER
        assump[col].fill = HEADER_FILL
    for i, (label, value, note) in enumerate(rows, start=4):
        assump.cell(row=i, column=1, value=label)
        assump.cell(row=i, column=2, value=float(value)).font = BLUE
        assump.cell(row=i, column=3, value=note)
    assump["A14"] = "目标投产比下限（利润约束）"
    assump["B14"] = "=IF(B4*(1-B6)=0,0,1/(B4*(1-B6)))"
    assump["A15"] = "目标去退费比上限（利润约束）"
    assump["B15"] = "=MAX(0,(B4-B5)/(1-B6))"
    assump["A16"] = "目标投产比（取严）"
    assump["B16"] = "=MAX(B14,B7)"
    assump["A17"] = "目标去退费比（取严）"
    assump["B17"] = "=IF(B15=0,B8,MIN(B15,B8))"
    assump["A18"] = "目标GSV（净）"
    assump["B18"] = "=B9"
    assump["A19"] = "目标GMV（毛）"
    assump["B19"] = "=IF(B10=0,0,B9/(1-B10))"
    assump["A20"] = "目标推广花费（目标GSV×目标去退费比）"
    assump["B20"] = "=B18*B17"
    assump["A21"] = "进度系数"
    assump["B21"] = "=IF(B11=0,1,B12/B11)"
    assump["A22"] = "目标GSV进度（按已过天数）"
    assump["B22"] = "=B18*B21"
    assump["A23"] = "目标GMV进度（按已过天数）"
    assump["B23"] = "=B19*B21"
    for r in range(14, 24):
        assump.cell(row=r, column=2).font = BLACK
    assump["A25"] = "口径提示"
    assump["A25"].font = Font(bold=True)
    assump["A26"] = ("目标GSV（净）= 上期GSV；目标GMV（毛）= 上期GSV÷(1−上期退款率)。"
                     "推广费比的分母是 GSV，所以目标推广花费必须用目标GSV（净）×目标去退费比，"
                     "不能拿毛 GMV 乘净费比。总灯 = 两轴取更差的一盏（脚本合成规则；"
                     "原文按四场景分别决策，未定义单灯）。")
    assump["A26"].fill = YELLOW_FILL
    for col, width in (("A", 26), ("B", 16), ("C", 52)):
        assump.column_dimensions[col].width = width

    raw = book.create_sheet("原始数据")
    raw.append(["商品ID", "名称", "分组", "阶段", "GMV", "退款金额", "访客数",
                "支付人数", "推广花费", "推广点击量", "推广成交金额", "间接成交占比"])
    for cell in raw[1]:
        cell.font = HEADER
        cell.fill = HEADER_FILL
    for row in items:
        cur = row["current"]
        raw.append([row["id"], row["name"], row["group"], row["stage"],
                    cur["gmv"], cur["refund"], cur["visitors"], cur["buyers"],
                    cur["cost"], cur["clicks"], cur["ad_gmv"], cur["indirect_share"]])
    for cell_row in raw.iter_rows(min_row=2, max_row=raw.max_row, min_col=5, max_col=12):
        for cell in cell_row:
            cell.font = BLUE
    for col, width in (("A", 16), ("B", 34), ("C", 14), ("D", 12), ("E", 14),
                       ("F", 12), ("G", 10), ("H", 10), ("I", 12), ("J", 12),
                       ("K", 14), ("L", 12)):
        raw.column_dimensions[col].width = width

    sheet = book.create_sheet("单品报表")
    head = ["商品ID", "名称", "分组", "阶段", "GSV", "退款率", "转化率", "客单价",
            "投产比", "推广费比", "去退推广费比", "目标投产比", "目标去退费比",
            "投产灯", "费比灯", "总灯", "场景", "推广花费", "推广成交金额"]
    sheet.append(head)
    for cell in sheet[1]:
        cell.font = HEADER
        cell.fill = HEADER_FILL
    for idx, row in enumerate(items, start=2):
        src = idx  # 原始数据同序
        sheet.cell(row=idx, column=1, value=f"='原始数据'!A{src}").font = GREEN
        sheet.cell(row=idx, column=2, value=f"='原始数据'!B{src}").font = GREEN
        sheet.cell(row=idx, column=3, value=f"='原始数据'!C{src}").font = GREEN
        sheet.cell(row=idx, column=4, value=f"='原始数据'!D{src}").font = GREEN
        sheet.cell(row=idx, column=5, value=f"='原始数据'!E{src}-'原始数据'!F{src}").font = BLACK
        sheet.cell(row=idx, column=6, value=f"=IF('原始数据'!E{src}=0,0,'原始数据'!F{src}/'原始数据'!E{src})").font = BLACK
        sheet.cell(row=idx, column=7, value=f"=IF('原始数据'!G{src}=0,0,'原始数据'!H{src}/'原始数据'!G{src})").font = BLACK
        sheet.cell(row=idx, column=8, value=f"=IF('原始数据'!H{src}=0,0,'原始数据'!E{src}/'原始数据'!H{src})").font = BLACK
        sheet.cell(row=idx, column=9, value=f"=IF('原始数据'!I{src}=0,0,'原始数据'!K{src}/'原始数据'!I{src})").font = BLACK
        sheet.cell(row=idx, column=10, value=f"=IF('原始数据'!E{src}=0,0,'原始数据'!I{src}/'原始数据'!E{src})").font = BLACK
        sheet.cell(row=idx, column=11, value=f"=IF((('原始数据'!E{src}-'原始数据'!F{src})=0),0,'原始数据'!I{src}/('原始数据'!E{src}-'原始数据'!F{src}))").font = BLACK
        sheet.cell(row=idx, column=12, value="=目标假设!$B$16").font = GREEN
        sheet.cell(row=idx, column=13, value="=目标假设!$B$17").font = GREEN
        sheet.cell(row=idx, column=14, value=f'=IF(I{idx}>=L{idx},"绿",IF(I{idx}>=L{idx}*0.8,"黄","红"))').font = BLACK
        sheet.cell(row=idx, column=15, value=f'=IF(K{idx}<=M{idx},"绿",IF(K{idx}<=M{idx}*1.2,"黄","红"))').font = BLACK
        sheet.cell(row=idx, column=16, value=f'=IF(OR(N{idx}="红",O{idx}="红"),"红",IF(OR(N{idx}="黄",O{idx}="黄"),"黄","绿"))').font = BLACK
        sheet.cell(row=idx, column=17, value=(
            f'=IF(AND(N{idx}="绿",O{idx}="绿"),"双绿",'
            f'IF(AND(N{idx}="红",O{idx}="红"),"双红",'
            f'IF(AND(N{idx}="红",O{idx}="黄"),"混合档：投产红/费比黄",'
            f'IF(N{idx}="绿",IF(O{idx}="红","投产绿/费比红","投产绿/费比黄"),'
            f'IF(O{idx}="绿",IF(N{idx}="红","投产红/费比绿","投产黄/费比绿"),'
            f'IF(N{idx}="红","投产红/费比红",'
            f'IF(O{idx}="红","投产黄/费比红","双黄")))))))')).font = BLACK
        # 原始量也搬过来：分组汇总要靠 SUMIF 聚合出比率，不能写死数值
        sheet.cell(row=idx, column=18, value=f"='原始数据'!I{src}").font = GREEN
        sheet.cell(row=idx, column=19, value=f"='原始数据'!K{src}").font = GREEN
    for col, width in (("A", 16), ("B", 34), ("C", 14), ("D", 12), ("E", 14), ("F", 10),
                       ("G", 10), ("H", 12), ("I", 10), ("J", 10), ("K", 12), ("L", 12),
                       ("M", 12), ("N", 8), ("O", 8), ("P", 8), ("Q", 18),
                       ("R", 12), ("S", 14)):
        sheet.column_dimensions[col].width = width

    grp = book.create_sheet("分组汇总")
    grp.append(["分组", "商品数", "GSV", "推广花费", "推广成交金额", "投产比",
                "去退推广费比", "投产灯", "费比灯", "总灯"])
    for cell in grp[1]:
        cell.font = HEADER
        cell.fill = HEADER_FILL
    last_row = len(items) + 1
    for idx, (name, agg) in enumerate(sorted(groups.items(), key=lambda kv: -kv[1]["gsv"]), start=2):
        grp.cell(row=idx, column=1, value=name).font = BLUE
        grp.cell(row=idx, column=2, value=agg["n"]).font = BLUE
        grp.cell(row=idx, column=3, value=f"=SUMIF(单品报表!$C$2:$C${last_row},A{idx},单品报表!$E$2:$E${last_row})").font = BLACK
        grp.cell(row=idx, column=4, value=f"=SUMIF(单品报表!$C$2:$C${last_row},A{idx},单品报表!$R$2:$R${last_row})").font = BLACK
        grp.cell(row=idx, column=5, value=f"=SUMIF(单品报表!$C$2:$C${last_row},A{idx},单品报表!$S$2:$S${last_row})").font = BLACK
        grp.cell(row=idx, column=6, value=f"=IF(D{idx}=0,0,E{idx}/D{idx})").font = BLACK
        grp.cell(row=idx, column=7, value=f"=IF(C{idx}=0,0,D{idx}/C{idx})").font = BLACK
        grp.cell(row=idx, column=8, value=f'=IF(F{idx}>=目标假设!$B$16,"绿",IF(F{idx}>=目标假设!$B$16*0.8,"黄","红"))').font = BLACK
        grp.cell(row=idx, column=9, value=f'=IF(G{idx}<=目标假设!$B$17,"绿",IF(G{idx}<=目标假设!$B$17*1.2,"黄","红"))').font = BLACK
        grp.cell(row=idx, column=10, value=f'=IF(OR(H{idx}="红",I{idx}="红"),"红",IF(OR(H{idx}="黄",I{idx}="黄"),"黄","绿"))').font = BLACK
    for col, width in (("A", 18), ("B", 10), ("C", 14), ("D", 14), ("E", 16), ("F", 10),
                       ("G", 14), ("H", 8), ("I", 8), ("J", 8)):
        grp.column_dimensions[col].width = width

    check = book.create_sheet("口径校验")
    check["A1"] = "口径校验（改假设或换数据后应全部为「通过」）"
    check["A1"].font = Font(bold=True)
    check.append([])
    check.append(["检查项", "公式", "结果"])
    for cell in check[3]:
        cell.font = HEADER
        cell.fill = HEADER_FILL
    last = len(items) + 1
    checks = [
        ("GSV = GMV − 退款", f"=IF(ABS(单品报表!E2-('原始数据'!E2-'原始数据'!F2))<0.01,\"通过\",\"不通过\")"),
        ("投产比 = 推广成交 ÷ 花费", f"=IF(ABS(单品报表!I2-('原始数据'!K2/'原始数据'!I2))<0.0001,\"通过\",\"不通过\")"),
        ("去退费比 = 花费 ÷ GSV", f"=IF(ABS(单品报表!K2-('原始数据'!I2/('原始数据'!E2-'原始数据'!F2)))<0.0001,\"通过\",\"不通过\")"),
        ("目标投产比 ≥ 利润约束下限", "=IF(目标假设!B16>=目标假设!B14-0.0001,\"通过\",\"不通过\")"),
        ("目标去退费比 ≤ 利润约束上限", "=IF(目标假设!B17<=目标假设!B15+0.0001,\"通过\",\"不通过\")"),
        ("目标GSV（净）= 上期GSV", "=IF(ABS(目标假设!B18-目标假设!B9)<0.01,\"通过\",\"不通过\")"),
        ("目标GMV（毛）= 上期GSV ÷ (1−上期退款率)", "=IF(ABS(目标假设!B19-目标假设!B9/(1-目标假设!B10))<0.01,\"通过\",\"不通过\")"),
        ("目标推广花费 = 目标GSV×目标去退费比（净×净）", "=IF(ABS(目标假设!B20-目标假设!B18*目标假设!B17)<0.01,\"通过\",\"不通过\")"),
        ("目标GSV进度 = 目标GSV×进度系数", "=IF(ABS(目标假设!B22-目标假设!B18*目标假设!B21)<0.01,\"通过\",\"不通过\")"),
        ("分组GSV合计 = 单品GSV合计", f"=IF(ABS(SUM(分组汇总!C2:C{len(groups) + 1})-SUM(单品报表!E2:E{last}))<0.01,\"通过\",\"不通过\")"),
        ("分组推广花费合计 = 单品推广花费合计", f"=IF(ABS(SUM(分组汇总!D2:D{len(groups) + 1})-SUM(单品报表!R2:R{last}))<0.01,\"通过\",\"不通过\")"),
    ]
    for i, (label, formula) in enumerate(checks, start=4):
        check.cell(row=i, column=1, value=label)
        check.cell(row=i, column=2, value=formula).font = BLACK
    for col, width in (("A", 36), ("B", 30), ("C", 12)):
        check.column_dimensions[col].width = width

    book.save(path)


# ---------------------------------------------------------------- 编排


def run_excel_channel(args) -> int:
    data = load_excel_channel(args.input)
    current_records = list(data["current"].values())
    base_records = list(data["base"].values())
    if not current_records:
        sys.exit("「本月数据」里没有可用的商品行（商品ID 全为空或只有汇总行）")

    # 大盘用模板自己的汇总行；明细合计只作分组汇总与口径对账用。
    # ⚠️ 实测两者不相等 —— 用明细合计当大盘会把投产比与费比算偏。
    current = data.get("store_current")
    base = data.get("store_base")
    if current is None:
        current = data["item_agg_current"]
    if base is None:
        base = data["item_agg_base"] if base_records else current
    item_agg = data["item_agg_current"]

    # 天数反推：日均GMV = GMV ÷ 天数
    # ⚠️ 口径陷阱 —— 模板里「上月日均GMV」是**整月**日均（8 月 31 天），
    # 「本月日均GMV」是**已过天数**日均（数据截止 9/25 = 25 天）。两者不同义。
    elapsed = args.elapsed_days
    if elapsed is None:
        day_avg = num_from_column(args.input, "本月数据", "日均GMV")
        elapsed = int(round(current["gmv"] / day_avg)) if day_avg > 0 else args.period_days
    period = args.period_days or elapsed

    targets = derive_targets(base, current, args.gross_margin, args.opex_rate,
                             elapsed, period)

    items = []
    groups: dict[str, dict] = {}
    stages: dict[str, dict] = {}
    for item_id, rec in data["current"].items():
        verdict = judge(rec, targets)
        items.append({"id": item_id, "name": rec["name"], "group": rec["group"],
                      "stage": rec["stage"], "current": rec, "judge": verdict})
        groups.setdefault(rec["group"], []).append(rec)
        stages.setdefault(rec["stage"], []).append(rec)
    groups = {k: aggregate(v) for k, v in groups.items()}
    stages = {k: aggregate(v) for k, v in stages.items()}

    recon = data.get("recon_current") or {}
    recon_lines = []
    for key, label in (("gmv", "GMV"), ("refund", "退款金额"), ("visitors", "访客数"),
                       ("buyers", "支付人数"), ("clicks", "推广点击量"),
                       ("cost", "推广花费"), ("ad_gmv", "推广成交金额")):
        info = recon.get(key)
        if not info:
            continue
        recon_lines.append(
            f"| {label} | {money(current[key])} | {money(item_agg[key])} | "
            f"{money(info['diff'])} | {'对得上' if info['matched'] else '对不上'} |")

    note = (f"> 数据源：{args.input}｜本期 {elapsed} 天已过 / 目标周期 {period} 天"
            f"｜毛利率 {pct(args.gross_margin)}｜运营成本率 {pct(args.opex_rate)}\n"
            f"> 目标口径：利润约束（profit-model 盈亏平衡投产比）+ 历史基线"
            f"（《推广红绿灯》模板预估目标链），两者取严。")
    if args.gross_margin <= 0:
        note += ("\n> ⚠️ **没有给毛利率**，利润约束轨道是关的 —— "
                 "目标投产比只取历史基线，目标去退费比也只取历史基线。"
                 "要开利润约束，用 `--gross-margin` 传入。")
    if args.opex_rate <= 0:
        note += ("\n> ⚠️ **没有给运营成本率**，目标去退费比的利润约束上限"
                 "只算了毛利率那一半，会偏松。")
    title = f"推广红绿灯报表 · {dt.date.today().isoformat()}"

    if args.out_md:
        text = render_markdown([current], targets, current, base, groups, stages,
                               items, title, note, recon_lines, item_agg)
        with open(args.out_md, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"已写出 Markdown 报表：{args.out_md}")
    if args.out_csv:
        write_csv(args.out_csv, items)
        print(f"已写出 CSV 明细：{args.out_csv}")
    if args.out_xlsx:
        write_excel_report(args.out_xlsx, items, targets, current, base, groups, title)
        print(f"已写出 Excel 报表（活公式）：{args.out_xlsx}")

    verdict = judge(current, targets)
    print()
    print(f"大盘：投产比 {current['roi']:.3f}（目标 {targets['target_roi']:.3f}，{verdict['roi_lamp']}）"
          f"｜去退费比 {pct(current['fee_rate_net'])}（目标 {pct(targets['target_fee_net'])}，{verdict['fee_lamp']}）"
          f"｜总灯 {verdict['overall']}｜场景 {verdict['scene']}")
    print(f"动作：{verdict['action']}")
    print(f"依据：{verdict['basis']}")
    return 0


def num_from_column(path: str, sheet_hint: str, column_hint: str) -> float:
    """从某张表里取第一行的某列（用于反推天数等）。取不到就 0。"""
    try:
        import openpyxl
    except ImportError:
        return 0.0
    try:
        book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception:
        return 0.0
    try:
        for name in book.sheetnames:
            if sheet_hint not in name:
                continue
            rows = list(book[name].iter_rows(values_only=True))
            if not rows:
                continue
            header = [str(h).strip() if h is not None else "" for h in rows[0]]
            for i, head in enumerate(header):
                if head == column_hint and len(rows) > 1:
                    return num(rows[1][i]) if i < len(rows[1]) else 0.0
    finally:
        book.close()
    return 0.0


def is_whole_month(begin: dt.date, end: dt.date) -> bool:
    """窗口是否正好是一个自然月。"""
    if (begin.year, begin.month) != (end.year, end.month):
        return False
    last = (dt.date(begin.year + (begin.month == 12), begin.month % 12 + 1, 1)
            - dt.timedelta(days=1))
    return begin.day == 1 and end == last


def shop_record(payload: dict) -> dict:
    """把一个店的一段区间拼成一条「店铺级」记录，口径与 Excel 通道对齐。

    口径选择（每一项都标来源，报告里也逐行标）：
      · GMV / 退款 / GSV —— **ERP 订单口径**（销售金额、退货金额，按订单日期、类型=真实）。
        退款率必须与分母同源，所以费比轴统一用 ERP 口径。
      · 推广花费 —— core_daily 四项逐日相加（全站/关键词/精准人群/智能场景）。
        ERP 的「推广费用」只有月末一行快照，不能按天 sum。
      · 投产比 —— 万相台三表（直接+间接）÷ 万相台花费。**分母与费比轴不是同一个数**，
        且间接成交跨计划归因可能重复计入，投产比会偏高。
      · 访客/买家/支付金额 —— core_daily（淘宝后台支付口径，与 ERP 销售金额不同义）。
    """
    lvl = payload["shop_level"]
    promo = payload.get("promo_total") or {}
    erp = payload.get("erp_level") or {}
    cost = lvl["cost"]
    direct = promo.get("direct", 0.0)
    indirect = promo.get("indirect", 0.0)
    ad_gmv = direct + indirect
    if num(erp.get("sales")) > 0:
        gmv = num(erp["sales"])
        refund = num(erp["returns"])
        gmv_source = "ERP 订单口径"
    else:
        gmv = lvl["gmv"]
        refund = lvl["refund_cash"]
        gmv_source = "core_daily 支付金额（ERP 无数据；退款为当天发生额，仅近似）"
    gsv = gmv - refund
    rec = {
        "gmv": gmv, "refund": refund, "gsv": gsv,
        "gmv_source": gmv_source,
        "gmv_paid": lvl["gmv"], "refund_cash": lvl["refund_cash"],
        "visitors": lvl["visitors"], "buyers": lvl["buyers"],
        "clicks": promo.get("clicks", 0.0), "cost": cost,
        "ad_gmv": ad_gmv, "ad_direct": direct, "ad_indirect": indirect,
        "days": lvl["days"],
        "promo_cost": promo.get("cost", 0.0),
        "promo_baobei_cost": promo.get("baobei_cost", 0.0),
        "promo_plans": promo.get("plans", 0),
        "promo_month_lo": promo.get("month_lo"),
        "promo_month_hi": promo.get("month_hi"),
    }
    rec["refund_rate"] = safe_div(rec["refund"], rec["gmv"])
    rec["aov"] = safe_div(lvl["gmv"], lvl["buyers"])       # 客单价用 core_daily 支付口径
    rec["cvr"] = safe_div(lvl["buyers"], lvl["visitors"])
    rec["roi"] = safe_div(ad_gmv, promo.get("cost", 0.0))
    rec["fee_rate"] = safe_div(cost, rec["gmv"])
    rec["fee_rate_net"] = safe_div(cost, rec["gsv"])
    rec["ad_share"] = safe_div(ad_gmv, rec["gmv"])
    rec["indirect_share"] = safe_div(indirect, ad_gmv)
    rec["cpc"] = safe_div(promo.get("cost", 0.0), rec["clicks"])
    rec["cpa"] = safe_div(cost, rec["visitors"])
    return rec


def run_pg_channel(args) -> int:
    shops = SHOP_SCHEMA_SUFFIXES if args.pg_shop == "all" else [args.pg_shop]
    end = args.pg_end or dt.date.today()
    begin = args.pg_begin or (end - dt.timedelta(days=29))
    span = (end - begin).days + 1
    base_begin = begin - dt.timedelta(days=span)
    base_end = begin - dt.timedelta(days=1)
    lines = [f"# 推广红绿灯 · 店铺/计划级（PG 通道）", "",
             f"> 数据源：本机 PostgreSQL｜本期 {begin} ~ {end}（{span} 天）"
             f"｜上期基线 {base_begin} ~ {base_end}",
             "> 粒度：店铺级 + 万相台计划级。**商品级红绿灯请走 Excel 通道** —— "
             "商品级 GMV/访客/退款率在生产库里没有对应字段。", ""]
    for shop in shops:
        payload = pg_load_shop(shop, begin, end)
        if payload.get("error"):
            lines.append(f"## {shop}")
            lines.append("")
            lines.append(f"⚠️ {payload['error']}")
            lines.append("")
            continue
        base_payload = pg_load_shop(shop, base_begin, base_end)
        cur = shop_record(payload)
        if base_payload.get("error"):
            base = dict(cur)
            base_note = f"⚠️ 上期基线取不到（{base_payload['error']}），目标退化为当期自比"
        else:
            base = shop_record(base_payload)
            base_note = ""
        gm = payload.get("gross_margin") or 0.0
        opex = args.opex_rate
        elapsed = args.elapsed_days or cur["days"]
        targets = derive_targets(base, cur, gm, opex, elapsed, cur["days"])
        verdict = judge(cur, targets)
        promo = payload.get("promo_total") or {}
        lines.append(f"## {shop}")
        lines.append("")
        lines.append("| 指标 | 口径 | 本期 | 上期基线 |")
        lines.append("|---|---|---|---|")
        lines.append(f"| 区间天数 | — | {cur['days']} | {base['days']} |")
        lines.append(f"| GMV | {cur['gmv_source']} | {money(cur['gmv'])} | {money(base['gmv'])} |")
        lines.append(f"| 退款金额 | {cur['gmv_source']} | {money(cur['refund'])} | {money(base['refund'])} |")
        lines.append(f"| 退款率 | {cur['gmv_source']} | {pct(cur['refund_rate'])} | {pct(base['refund_rate'])} |")
        lines.append(f"| GSV | GMV−退款 | {money(cur['gsv'])} | {money(base['gsv'])} |")
        lines.append(f"| 支付金额（对照） | core_daily 淘宝后台 | {money(cur['gmv_paid'])} | {money(base['gmv_paid'])} |")
        lines.append(f"| 当日退款发生额（对照） | core_daily 当天发生额 | {money(cur['refund_cash'])} | {money(base['refund_cash'])} |")
        lines.append(f"| 访客数 | core_daily | {cur['visitors']:,.0f} | {base['visitors']:,.0f} |")
        lines.append(f"| 支付买家数 | core_daily | {cur['buyers']:,.0f} | {base['buyers']:,.0f} |")
        lines.append(f"| 支付转化率 | core_daily | {pct(cur['cvr'])} | {pct(base['cvr'])} |")
        lines.append(f"| 客单价 | core_daily 支付金额 ÷ 买家数 | {cur['aov']:.2f} | {base['aov']:.2f} |")
        lines.append(f"| 推广花费 | core_daily 四项逐日相加 | {money(cur['cost'])} | {money(base['cost'])} |")
        lines.append(f"| 推广花费 | 万相台按计划ID去重并集 | {money(cur['promo_cost'])} | {money(base['promo_cost'])} |")
        lines.append(f"| 推广花费（对照） | 万相台宝贝表视图 | {money(cur['promo_baobei_cost'])} | {money(base['promo_baobei_cost'])} |")
        lines.append(f"| 推广计划数 | 万相台去重后 | {cur['promo_plans']} | {base['promo_plans']} |")
        lines.append(f"| 推广成交金额 | 万相台 直接+间接 | {money(cur['ad_gmv'])} | {money(base['ad_gmv'])} |")
        lines.append(f"| 投产比 | 万相台（直接+间接）÷ 万相台花费 | {cur['roi']:.3f} | {base['roi']:.3f} |")
        lines.append(f"| 间接成交占比 | 万相台 | {pct(cur['indirect_share'])} | {pct(base['indirect_share'])} |")
        lines.append(f"| 推广费比（÷GMV） | ERP 订单口径 | {pct(cur['fee_rate'])} | {pct(base['fee_rate'])} |")
        lines.append(f"| 去退推广费比（÷GSV） | ERP 订单口径 | {pct(cur['fee_rate_net'])} | {pct(base['fee_rate_net'])} |")
        lines.append(f"| 毛利率 | ERP（商家实收−实发成本）÷商家实收 | {pct(gm) if gm else '未取到 ⚠️'} | — |")
        lines.append("")
        lines.append("| 目标 | 取值 | 依据 |")
        lines.append("|---|---|---|")
        lines.append(f"| 目标投产比 | {targets['target_roi']:.3f} | "
                     f"max(利润约束 {targets['be_roi']:.3f}, 上期基线 {targets['base_roi']:.3f}) |")
        lines.append(f"| 目标去退费比 | {pct(targets['target_fee_net'])} | "
                     f"min(利润约束 {pct(targets['max_fee_net'])}, 上期基线 {pct(targets['base_fee_net'])}) |")
        lines.append(f"| 目标 GSV（净） | {money(targets['target_gsv'])} | 上期 GSV |")
        lines.append(f"| 目标推广花费 | {money(targets['target_cost'])} | 目标GSV×目标去退费比 |")
        lines.append(f"| 投产灯 | {verdict['roi_lamp']} | 目标 {targets['target_roi']:.3f} |")
        lines.append(f"| 费比灯 | {verdict['fee_lamp']} | 目标 {pct(targets['target_fee_net'])} |")
        lines.append(f"| 总灯 | {verdict['overall']} | 两轴取更差的一盏（脚本合成规则） |")
        lines.append(f"| 场景 | {verdict['scene']} | {verdict['basis']} |")
        lines.append(f"| 动作 | {verdict['action']} | |")
        lines.append("")
        if base_note:
            lines.append(f"> {base_note}")
            lines.append("")
        lines.append("> ⚠️ 口径提示：① GMV/退款/GSV 用 **ERP 订单口径**（按订单日期、类型=真实），"
                     "core_daily 的「成功退款金额」是当天发生额（含历史订单退款），只能当对照看；"
                     "② 投产比的分母是万相台去重后的花费，与费比的分母（ERP 销售金额）不是同一个数；"
                     "③ 间接成交跨计划归因可能重复计入，投产比偏高；"
                     "④ 万相台是**月度快照**（stat_date 每月只有 1 个值，实测为当月 1 号），"
                     "推广数据取的是整月快照，按任意日期区间过滤会静默返回 0 行；"
                     "⑤ 万相台三张表是同一批计划的不同维度视图，**不能相加**"
                     "（实测相加会把花费算两倍），本表按计划ID去重。")
        if not is_whole_month(begin, end):
            lines.append(f"> ⚠️ 本窗口 {begin}~{end} **不是自然月** —— "
                         f"core_daily/ERP 按逐日取，推广侧只能取整月快照"
                         f"（{cur['promo_month_lo']}~{cur['promo_month_hi']}），两边口径不对齐，"
                         f"结论请按自然月复核。")
        for err in payload.get("promo_errors") or []:
            lines.append(f"> ⚠️ {err}")
        lines.append("")
        lines.append("### 计划体检")
        lines.append("")
        lines.append("| 类型 | 计划 | 花费 | 直接成交 | 间接成交 | 投产 | 新客数 | 判读 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for plan in payload["plans"][:20]:
            findings = plan_findings(plan)
            roi = safe_div(plan["direct"] + plan["indirect"], plan["cost"])
            lines.append(
                f"| {plan['kind']} | {plan['plan']} | {money(plan['cost'])} | "
                f"{money(plan['direct'])} | {money(plan['indirect'])} | {roi:.3f} | "
                f"{plan['newcust']:.0f} | {'；'.join(findings) if findings else '—'} |")
        lines.append("")
    text = "\n".join(lines)
    if args.out_md:
        with open(args.out_md, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"已写出 Markdown 报表：{args.out_md}")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- 自检


def _build_probe_workbook(path: str, break_diff_row: bool = False) -> None:
    """造一份《推广红绿灯》结构的最小表：大盘行 + 明细行 + 差额行 + 总计行。

    结构刻意复刻真实模板 —— 实测真实模板里 **大盘行 ≠ 明细合计**，
    差额藏在明细区中间的另一条汇总行里（标签同样是「(空白)」）。
    """
    import openpyxl
    book = openpyxl.Workbook()
    cur = book.active
    cur.title = "本月数据"
    cur.append(["商品ID", "GMV", "退款金额", "访客数", "支付人数", "推广点击量",
                "推广花费", "推广成交金额", "间接成交占比", "日均GMV"])
    cur.append(["(空白)", 1000, 400, 200, 10, 50, 250, 900, 0.3, 40])
    cur.append(["A", 600, 240, 120, 6, 30, 150, 540, 0.3, 24])
    cur.append(["B", 300, 120, 60, 3, 15, 75, 270, 0.3, 12])
    cur.append(["(空白)", 7 if break_diff_row else 100, 40, 20, 1, 5, 25, 90, 0.3, 4])
    cur.append(["总计", 1000, 400, 200, 10, 50, 250, 900, 0.3, 40])

    prev = book.create_sheet("上月数据")
    prev.append(["商品ID", "上月GMV", "上月退款金额", "上月访客数", "上月支付人数",
                 "上月推广点击量", "上月推广花费", "上月推广成交金额", "上月间接成交占比"])
    prev.append(["(空白)", 800, 300, 160, 8, 40, 200, 700, 0.25])
    prev.append(["A", 500, 180, 100, 5, 25, 125, 450, 0.25])
    prev.append(["B", 250, 100, 50, 2, 12, 60, 220, 0.25])
    prev.append(["(空白)", 50, 20, 10, 1, 3, 15, 30, 0.25])
    prev.append(["总计", 800, 300, 160, 8, 40, 200, 700, 0.25])

    attr = book.create_sheet("宝贝清单")
    attr.append(["商品ID", "品类名称", "价格带层级", "宝贝名称", "货品成长阶段"])
    attr.append(["A", "棉服", "中", "棉服A", "冷启期"])
    attr.append(["B", "外套", "高", "外套B", "成长期"])
    book.save(path)


def self_test_excel_discovery() -> list[str]:
    """验大盘识别：大盘取模板汇总行，不是明细相加；差额能被差额行解释。"""
    import tempfile
    problems: list[str] = []
    path = os.path.join(tempfile.gettempdir(), "_rg_probe_workbook.xlsx")
    try:
        _build_probe_workbook(path)
        data = load_excel_channel(path)
        if len(data["current"]) != 2:
            problems.append(f"明细行数应为 2，实际 {len(data['current'])}")
        if abs(data["store_current"]["gmv"] - 1000.0) > 1e-9:
            problems.append("大盘应取模板汇总行的 1000")
        if abs(data["item_agg_current"]["gmv"] - 900.0) > 1e-9:
            problems.append(f"明细合计应为 900，实际 {data['item_agg_current']['gmv']}")
        if abs(data["store_base"]["gmv"] - 800.0) > 1e-9:
            problems.append("上月大盘应取 800")
        rec = data["recon_current"]["gmv"]
        if abs(rec["diff"] - 100.0) > 1e-9:
            problems.append(f"大盘−明细合计的差额应为 100，实际 {rec['diff']}")
        if not rec["matched"]:
            problems.append("差额行应能解释大盘与明细合计的差额")
        if data["current"]["A"]["group"] != "棉服":
            problems.append("宝贝清单的品类名称未带进明细")

        # 反向对照：把差额行改坏，对账必须报「对不上」而不是照样通过
        _build_probe_workbook(path, break_diff_row=True)
        data2 = load_excel_channel(path)
        if data2["recon_current"]["gmv"]["matched"]:
            problems.append("差额行对不上时仍被判为 matched —— 校验没有牙")
    except Exception as exc:
        problems.append(f"大盘识别自检抛异常：{exc}")
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    return problems


def self_test() -> int:
    """造数据验算：既要算对，也要算坏的时候不崩、报得清楚。"""
    failures: list[str] = []
    total_checks = 0

    def check(label: str, condition: bool) -> None:
        nonlocal total_checks
        total_checks += 1
        if not condition:
            failures.append(label)

    # 1. 口径：客单价用 GMV、费比分母分毛净、ROI 分子含间接成交
    rec = build_record("T1", "样本", "组A", "冷启期",
                       gmv=1000.0, refund=400.0, visitors=200.0, buyers=10.0,
                       clicks=50.0, cost=250.0, ad_gmv=900.0, indirect_gmv=300.0)
    check("GSV = GMV − 退款", abs(rec["gsv"] - 600.0) < 1e-9)
    check("退款率 = 退款 ÷ GMV", abs(rec["refund_rate"] - 0.4) < 1e-9)
    check("客单价 = GMV ÷ 支付人数（不是 GSV 口径）", abs(rec["aov"] - 100.0) < 1e-9)
    check("转化率 = 支付人数 ÷ 访客数", abs(rec["cvr"] - 0.05) < 1e-9)
    check("推广费比 = 花费 ÷ GMV（毛）", abs(rec["fee_rate"] - 0.25) < 1e-9)
    check("去退推广费比 = 花费 ÷ GSV（净）", abs(rec["fee_rate_net"] - 250.0 / 600.0) < 1e-9)
    check("投产比分子含间接成交", abs(rec["roi"] - 900.0 / 250.0) < 1e-9)
    check("间接成交占比", abs(rec["indirect_share"] - 300.0 / 900.0) < 1e-9)

    # 2. 坏数据：分母为零不得抛异常
    zero = build_record("T0", "零值", "", "", gmv=0.0, refund=0.0, visitors=0.0,
                        buyers=0.0, clicks=0.0, cost=0.0, ad_gmv=0.0, indirect_gmv=0.0)
    check("全零不崩", zero["roi"] == 0.0 and zero["fee_rate_net"] == 0.0)
    neg = build_record("T2", "退款大于GMV", "", "", gmv=100.0, refund=150.0,
                       visitors=10.0, buyers=1.0, clicks=1.0, cost=10.0,
                       ad_gmv=10.0, indirect_gmv=0.0)
    check("GSV 为负可算不崩", abs(neg["gsv"] - (-50.0)) < 1e-9)

    # 3. 红绿灯边界
    check("投产=目标 → 绿", lamp_roi(3.0, 3.0) == GREEN)
    check("投产=目标×0.8 → 黄", lamp_roi(2.4, 3.0) == YELLOW)
    check("投产<目标×0.8 → 红", lamp_roi(2.39, 3.0) == RED)
    check("费比=目标 → 绿", lamp_fee(0.2, 0.2) == GREEN)
    check("费比=目标×1.2 → 黄", lamp_fee(0.24, 0.2) == YELLOW)
    check("费比>目标×1.2 → 红", lamp_fee(0.25, 0.2) == RED)
    check("场景：双绿", scene_of(GREEN, GREEN) == "双绿")
    check("场景：投产绿费比红", scene_of(GREEN, RED) == "投产绿/费比红")
    check("场景：投产红费比绿", scene_of(RED, GREEN) == "投产红/费比绿")
    check("场景：双红", scene_of(RED, RED) == "双红")
    check("场景：投产绿费比黄", scene_of(GREEN, YELLOW) == "投产绿/费比黄")
    check("场景：投产黄费比绿", scene_of(YELLOW, GREEN) == "投产黄/费比绿")
    check("场景：双黄", scene_of(YELLOW, YELLOW) == "双黄")
    check("场景：投产黄费比红", scene_of(YELLOW, RED) == "投产黄/费比红")
    check("场景：红+黄 是混合档并带出处", "混合档" in scene_of(RED, YELLOW))
    check("九种灯组合全部有归属", all(
        (a, b) in SCENE_ACTION for a in (GREEN, YELLOW, RED) for b in (GREEN, YELLOW, RED)))
    check("每种灯组合都有动作与依据", all(
        len(v) == 3 and v[1] and v[2] for v in SCENE_ACTION.values()))
    check("黄灯动作含观望", "观望" in scene_action(GREEN, YELLOW)[1])
    check("双红动作含 50%-80%", "50%-80%" in scene_action(RED, RED)[1])
    check("双绿动作含 20%-30%", "20%-30%" in scene_action(GREEN, GREEN)[1])

    # 4. 双轨取严
    base = aggregate([build_record("A", "a", "g", "s", 1000, 200, 100, 10, 50, 300, 600, 0)])
    cur = aggregate([build_record("A", "a", "g", "s", 1000, 200, 100, 10, 50, 300, 600, 0)])
    t = derive_targets(base, cur, gross_margin=0.30, opex_rate=0.05,
                       elapsed_days=15, period_days=30)
    check("利润约束下限 = 1÷[毛利率×(1−退款率)]",
          abs(t["be_roi"] - 1.0 / (0.30 * (1 - cur["refund_rate"]))) < 1e-9)
    check("利润约束上限 = (毛利率−运营成本率)÷(1−退款率)",
          abs(t["max_fee_net"] - (0.30 - 0.05) / (1 - cur["refund_rate"])) < 1e-9)
    check("目标投产比 = max(下限, 基线)", t["target_roi"] == max(t["be_roi"], t["base_roi"]))
    check("目标去退费比 = min(上限, 基线)",
          abs(t["target_fee_net"] - min(t["max_fee_net"], t["base_fee_net"])) < 1e-9)
    check("目标GSV（净）= 上期GSV", abs(t["target_gsv"] - base["gsv"]) < 1e-9)
    check("目标GMV（毛）= 上期GSV÷(1−上期退款率)",
          abs(t["target_gmv"] - base["gsv"] / (1 - base["refund_rate"])) < 1e-9)
    check("目标花费 = 目标GSV（净）×目标去退费比，毛净不混用",
          abs(t["target_cost"] - t["target_gsv"] * t["target_fee_net"]) < 1e-9)
    check("目标流量 = 目标GMV÷(上期客单价×上期转化率)",
          abs(t["target_visitors"] - t["target_gmv"] / (base["aov"] * base["cvr"])) < 1e-9)
    check("目标进度按已过天数折算", abs(t["target_gsv_to_date"] - t["target_gsv"] * 0.5) < 1e-9)

    # 5. 坏数据：缺表必须明确报错，不是静默空报表
    try:
        load_excel_channel("__不存在的文件__.xlsx")
        failures.append("缺文件时未报错")
    except SystemExit:
        pass
    except Exception as exc:
        failures.append(f"缺文件时抛了非 SystemExit：{exc}")

    # 6. 坏数据：商品ID 统一（用合成 ID，不用任何真实商品）
    check("数字型商品ID 归一", product_id(1000000000001.0) == "1000000000001")
    check("文本型商品ID 去尾零", product_id("1000000000001.0") == "1000000000001")
    check("空商品ID", product_id(None) == "")

    # 7. 坏数据：非数字金额不得抛异常
    check("脏金额转 0", num("abc") == 0.0 and num("1,234.5") == 1234.5 and num(None) == 0.0)
    check("百分号文本按百分数解析", abs(num("9.27%") - 0.0927) < 1e-12)

    # 8. 目标推广成交金额
    check("目标推广成交金额 = 目标GMV×上期推广成交占比",
          abs(t["target_ad_gmv"] - t["target_gmv"] * base["ad_share"]) < 1e-9)

    # 9. 大盘识别（真实表结构复刻）
    failures.extend(self_test_excel_discovery())

    if failures:
        print(f"❌ 自检失败 {len(failures)} 项：")
        for item in failures:
            print("   -", item)
        return 1
    print(f"✅ 自检通过：口径、红绿灯边界、双轨取严、大盘识别、坏数据鲁棒性共 {total_checks} 项断言全部成立")
    return 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推广红绿灯报表生成器")
    parser.add_argument("--input", help="Excel 通道输入：《推广红绿灯》模板或同结构导出表")
    parser.add_argument("--pg-shop", help="PG 通道：店铺名（haoyale 等）或 all")
    parser.add_argument("--pg-begin", help="PG 通道起始日期 YYYY-MM-DD")
    parser.add_argument("--pg-end", help="PG 通道结束日期 YYYY-MM-DD")
    parser.add_argument("--gross-margin", type=float, default=0.0,
                        help="毛利率（0~1），利润约束的输入")
    parser.add_argument("--opex-rate", type=float, default=0.0,
                        help="运营成本率（0~1），利润约束的输入")
    parser.add_argument("--period-days", type=int, default=30,
                        help="目标周期总天数（默认 30）")
    parser.add_argument("--elapsed-days", type=int, default=None,
                        help="已过天数（默认从本月日均GMV 反推）")
    parser.add_argument("--out-md", help="Markdown 报表输出路径")
    parser.add_argument("--out-csv", help="CSV 明细输出路径")
    parser.add_argument("--out-xlsx", help="Excel 报表输出路径（活公式）")
    parser.add_argument("--self-test", action="store_true", help="跑内置自检")
    args = parser.parse_args(argv)

    # 日期参数统一转成 date，传错格式要明确报错而不是崩在算术上
    for flag in ("pg_begin", "pg_end"):
        raw = getattr(args, flag)
        if raw:
            try:
                setattr(args, flag, dt.date.fromisoformat(raw))
            except ValueError:
                sys.exit(f"--{flag.replace('_', '-')} 不是合法日期（应为 YYYY-MM-DD）：{raw}")

    if args.self_test:
        return self_test()
    if args.input:
        return run_excel_channel(args)
    if args.pg_shop:
        return run_pg_channel(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

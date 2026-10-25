# skill-ecommercial

> 淘宝 / 天猫电商运营 Agent Skills —— 把一套 2013 页的运营知识库，编译成 agent 能直接执行的 20 本技能手册。

[![skills](https://img.shields.io/badge/skills-20-blue)](skills/)
[![layer](https://img.shields.io/badge/layer-L0%E2%86%92L3-green)](docs/ROADMAP.md)
[![chapters](https://img.shields.io/badge/chapters-95-lightgrey)](skills/)
[![source](https://img.shields.io/badge/source-taobao--operation-orange)](docs/SOURCE-NOTES.md)
[![source](https://img.shields.io/badge/source-taobao--operation-orange)](docs/SOURCE-NOTES.md)
[![ci](https://github.com/kizemo/skill-ecommercial/actions/workflows/validate-skills.yml/badge.svg)](https://github.com/kizemo/skill-ecommercial/actions/workflows/validate-skills.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[快速开始](#快速开始)** · **[安装](#安装)** · **[怎么用](#怎么用)** · **[技能清单](#技能清单)** · **[安装指南](docs/安装指南.md)** · **[使用说明书](docs/使用说明书.md)**

---

## 目录

- [这是什么](#这是什么)
- [为什么值得用](#为什么值得用)
- [核心特性](#核心特性)
- [最近更新](#最近更新)
- [快速开始](#快速开始)
- [安装](#安装)
- [怎么用](#怎么用)
- [技能清单](#技能清单)
- [一本技能长什么样](#一本技能长什么样)
- [数据来源与可信度](#数据来源与可信度)
- [项目结构](#项目结构)
- [质量保障](#质量保障)
- [文档索引](#文档索引)
- [路线图与边界](#路线图与边界)
- [常见问题](#常见问题)
- [参与贡献](#参与贡献)
- [License](#license)

---

## 这是什么

一套**能照着做**的电商运营方法论技能库，覆盖从选品、测款、推广、转化、客户资产，到数据诊断、大促作战、合规红线的完整链路。

来源是 `taobao-operation` Obsidian 知识库（2112 篇笔记 / 49MB / 10 大业务模块），经 GBRain 导入（2013 页 / 24077 个可检索片段）后逐条编译。

**它不是文档摘要。** 每一本技能交付的是：

| 交付什么 | 具体形态 |
|---|---|
| **框架名** | 用行业自己的语言（`汉堡包计划`、`尖刀连`、`3384 利润公式`、`领先率`、`多品多域`），不另造词 |
| **步骤** | 能落到"今天打开哪个后台、改哪个参数" |
| **判断标准** | 具体阈值，不写"要精细化运营"这种废话 |
| **停止条件** | 什么时候该停、什么时候该降级 |
| **误区与红线** | 知识库里那些真实踩过的坑 |

一句话区别：

> 资料告诉你「爆款有四个阶段」；这本技能告诉你**这个链接现在处在哪个阶段（LQ 公式怎么算）**、**该不该继续投**、**标签怎么叠**、**什么信号出现就切阶段**。

---

## 为什么值得用

### 对运营者：把「搜得到」变成「用得上」

知识库的问题从来不是缺内容，是**内容散在 2112 篇笔记里**——真到要判断"投产这么高为什么不赚钱"，翻半小时也找不到"真实投产去伪"这条公式在本场景的算法。

装上之后，每个高频问题都有固定入口和明确答案：

```
「这个链接投产很高但不赚钱，是真的吗？」
  → profit-model
  → 真实投产 = 投产 × (1−退款率) × (1−间接成交占比) × 拉新成交
  → 附带 3384 利润公式、盈亏平衡 ROI、斩杀线
```

### 对 agent 开发者：给模型「可判断的输入」

大模型最怕的是模糊指令。这套技能的结构就是为模型设计的：

- **`description` 就是索引** —— 每本都带一串触发关键词（"费比异常""投产去伪""禁用词"），宿主靠它自动匹配
- **`SKILL.md` 控制在 4000 tokens 以内** —— 最重要的内容前置，细节进 `chapters/` 按需加载，不占常驻预算
- **`cheatsheet.md` 是决策辅助不是术语表** —— 给阈值表、决策树、判据、陷阱；查名词去 `glossary.md` 就行
- **每本都有 `patterns.md`** —— 写明「何时用 / 怎么做 / 代价与风险」，让 agent 知道边界在哪

### 对团队与管理者：统一口径

同一个指标在不同人嘴里有不同算法，是运营团队最贵的内耗。这套技能把口径写死并交叉对账：

- 领先率四档（≥80% / 70-80% / 50-70% / <50% / <30%）
- 退款率按**订单日期**口径，不按当日退款发生额
- 红绿灯用**相对自身 7 日均值**判定，绝对红线单列（体验分 4.6、PXI 70/60、大促退款率 5%、放量 ≤50%）
- 素材冲突时显式标注「口径冲突，需复核」，不私自选一个

### 对数据侧：有一本是真能跑的

20 本里有两本不一样 —— [`daily-store-patrol`](skills/daily-store-patrol/) **直连 PostgreSQL**，把 ERP 每日订单/成本/推广费用 与 店铺侧流量/客户资产/万相台推广 接成一条每日巡店流水线，附可运行脚本；[`domain-growth-ops`](skills/domain-growth-ops/) 把智篆商业·老草老师的全域增长方法论（含**推广红绿灯**）编译成决策层手册。

对 7 家淘宝店实测跑通，输出红绿灯表、问题清单、机会清单、今日行动项：

```
### 机会项提示（由数据实算，非固定清单）

- 💰 **费比 21.84% 低于 7 日均值 34.89%** → 有预算回收空间，可加投赢家（`wanxiangtai-wujie`）
- 📈 **「手淘搜索」转化率 7.23%**（店铺均值 1.89%，访客 1,742）→ 被低估的来源，可加预算（`keyword-promo`）
- ✅ 大盘新客占比 86.12%（人数口径）达合格线 —— 但该口径在 7 店实测普遍 ≥86%，**判别力低**，拉新/收割以金额口径为准（见下）
- 🟡 **新客成交金额占比 67.35%**（50-70%）→ 资源浪费在收割，查定向与出价（`store-diagnosis`）
- 💤 **沉睡粉丝 9,049 ≥ 活跃粉丝 8,991** → 私域未激活，今日排召回（`customer-asset-ops`）
- 🚀 **加投候选 · 关键词 · 关键词计划_210200防褥疮坐垫A1拉新**（投产 3.86、新客 70、花费 4,123.63）→ 加预算，增幅 ≤50%（`wanxiangtai-wujie`）
```

> 以上为**真实运行输出**（好雅乐店 2026-10-22，7 店同日跑批中的一条），逐字摘录自 `scripts/daily_patrol.py` 的报告，非演示数据。

---

## 核心特性

- ✅ **20 本技能，四层架构** —— L0 总纲 → L1 体系层（8）→ L2 域层（9）→ L3 工具层（2），依赖方向单向，不循环
- ✅ **统一目录结构** —— 每本都是 `SKILL.md` + `chapters/` + `glossary.md` + `patterns.md` + `cheatsheet.md`，机器可校验
- ✅ **可运行脚本** —— 巡店脚本对 7 店实测跑通，口令走环境变量，不入库
- ✅ **自动质量门禁** —— 结构 / frontmatter / token 预算 / 占位符 / 交叉引用 / 决策性内容，10 项检查，CI 每次提交跑
- ✅ **跨宿主通用** —— Anthropic Agent Skills 开放格式，Claude Code / cc-haha / MiniMax Code / Cursor / Codex 都能装
- ✅ **4 种安装方式** —— 官方 skills CLI、仓库脚本、Claude Code 插件市场、手动拷贝
- ✅ **数字纪律** —— 阈值必须来自知识库原文或数据库实测，缺失标注「未验证」，冲突标注「口径冲突，需复核」

---

## 最近更新

**2026-10-25 · 补齐两个真实缺口 + 双宿主安装**

| 新增 | 位置 | 讲什么 |
|---|---|---|
| **老草测款方法** | `selection-testing` ch04 | 相同流量环境、半个月看转化、500 块两条退路、共鸣词包、点击单价进攻 |
| **双11 备战 2026** | `campaign-playbook` ch06 | 资产召回三类、10/15-11/14 节奏窗口、一品多链、SKU 级独立展示、规避系统比价、AI 视觉升级 |
| **双11 官方落地** | `campaign-playbook` ch07 | 活动准备四步曲、先涨后降价格管控、红线价、达摩盘双11 活动（**2024/2025 口径**） |

同时：`domain-growth-ops` 速查表补齐了 ch08 的预算配比与边际拐点阈值；仓库门禁维持 **20 skill / 0 error / 0 warn**，CI 每次 push 自动跑。

> 这三个章节的原始素材**本来就在** `taobao-operation` 知识库里，此前未被使用 —— 所以本库是持续从源库编译的，不是一次性快照。

---

## 快速开始

三步，大约两分钟。

**第 1 步 · 装**

```bash
npx skills add https://github.com/kizemo/skill-ecommercial -g -a '*' -s '*' -y --copy
```

> Windows 普通权限请保留 `--copy`（默认建符号链接需要管理员）。
> 只想先看看有哪些：`npx skills add https://github.com/kizemo/skill-ecommercial --list`

**第 2 步 · 重启宿主**

技能目录是在会话启动时扫描的，不重启不会生效。

**第 3 步 · 开口**

```
帮我巡一下店，看看费比和投产有没有问题
```

宿主会自动匹配到 `daily-store-patrol`（或先走 `taobao-ops-playbook` 路由）。

> 不想用 npx？见 [安装](#安装) 里的其它三种方式。

---

## 安装

### 方式 A · 官方 skills CLI（推荐，已实测）

```bash
npx skills add https://github.com/kizemo/skill-ecommercial --list    # 只列不装
npx skills add https://github.com/kizemo/skill-ecommercial -g -a '*' -s '*' -y --copy
```

| 参数 | 含义 |
|---|---|
| `-g` | 装到全局（个人级），不加则装到当前项目 |
| `-a '*'` | 装给所有已支持的 agent |
| `-s '*'` | 装全部 20 本 |
| `--copy` | 复制而非符号链接（Windows 非管理员必加） |
| `-y` | 跳过交互确认 |

### 方式 B · 仓库自带安装脚本

```bash
git clone https://github.com/kizemo/skill-ecommercial.git
cd skill-ecommercial

python scripts/install_skills.py --list-hosts   # 先看本机会装到哪里
python scripts/install_skills.py --host claude  # Claude Code / cc-haha
python scripts/install_skills.py --host minimax # MiniMax Code
```

常用参数：`--only daily-store-patrol,store-diagnosis`（只装指定几本）、`--dry-run`（只看不装）、`--force`（仓库更新后覆盖）、`--mode symlink`（省磁盘，Windows 需管理员）。

脚本会自动识别本机多个配置根里**哪个才是真身**（符号链接 / 空壳目录都会被排除），只复制目录，不改宿主配置、不写任何口令。

### 方式 C · Claude Code 插件市场

```
/plugin marketplace add kizemo/skill-ecommercial
/plugin install skill-ecommercial@skill-ecommercial
```

> ⚠️ **必须用 Git 方式 add**。用 `marketplace.json` 的直链 URL 时，相对路径不解析，会装空。

装完技能带命名空间：`/skill-ecommercial:store-diagnosis`。

### 方式 D · 手动拷贝

```bash
git clone --depth 1 https://github.com/kizemo/skill-ecommercial.git
cp -r skill-ecommercial/skills/* ~/.claude/skills/
```

### 各宿主的技能目录

| 宿主 | 个人级目录 | 项目级目录 |
|---|---|---|
| Claude Code / cc-haha | `~/.claude/skills/` | `.claude/skills/` |
| MiniMax Code | `~/.minimax/.minimax/skills/` | — |
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| OpenCode | `~/.agents/skills/` | `.agents/skills/` |
| Copilot CLI | `~/.agents/skills/` | `.github/skills/` |
| OpenClaw | `${OPENCLAW_STATE_DIR:-~/.openclaw}/skills/` | `skills/` |

> 完整说明（含常见问题）见 **[docs/安装指南.md](docs/安装指南.md)**。

---

## 怎么用

### 1 · 自然语言，宿主自动选（最省事）

每本的 `description` 都带触发关键词，直接说人话即可：

```
帮我巡一下店，看看费比和投产有没有问题
这个链接投产很高但不赚钱，是真的吗
大促前 30 天该做什么准备
主图点击率太低了怎么改
详情页里"最有效"这种词能用吗
```

### 2 · 斜杠命令，精确指定

```
/taobao-ops-playbook     # L0 总纲 / 路由
/store-diagnosis         # L1 店铺诊断
/daily-store-patrol      # L1 每日巡店（直连数据库）
/domain-growth-ops       # L1 全域增长操盘（推广红绿灯）
/profit-model            # L1 利润算账
/customer-asset-ops      # L1 客户资产
```

插件方式安装时带命名空间：`/skill-ecommercial:store-diagnosis`。

### 3 · 不知道用哪本？先走 L0 路由

`taobao-ops-playbook` 是整套技能库的入口，它自己不执行动作，只回答三件事：**我现在在哪一环？这一环该用哪本？关键公式和阈值是多少？**

或者直接查这张症状速查表：

| 你遇到的情况 | 打开哪本 |
|---|---|
| 不知道该用哪本、现在在哪一环 | `taobao-ops-playbook` |
| 每天开店要做一次全店体检 | `daily-store-patrol` |
| 费比突然变高，投产好看却不赚钱 | `store-diagnosis` → `profit-model` |
| 不知道哪个链接该加钱、该停 | `sabc-product-tiering` |
| 钱花在哪没生效 | `store-diagnosis` |
| 计划怎么搭、预算怎么加减 | `wanxiangtai-wujie` |
| 费比红线、推广红绿灯、该给谁加钱该停谁 | `domain-growth-ops` |
| 搜索没点击、排名被抢 | `keyword-promo` |
| 有流量没成交、主图/详情页要改 | `conversion-optimization` |
| 定价、活动空间、最低价 | `pricing-margin` |
| 大促节奏、蓄水、价盘 | `campaign-playbook` |
| 双11 备盘、链接矩阵、资产召回 | `campaign-playbook` |
| 新品测不出结果、测款没转化、要不要放弃 | `selection-testing` |
| 指标口径、老板要什么数 | `data-metrics` |
| 人群分层、召回、复购 | `customer-asset-ops` |
| 算账、盈亏平衡、投产去伪 | `profit-model` |
| 链接处在爆款哪个阶段、标签怎么叠 | `hit-product-lifecycle` |
| 主图素材、视觉升级 | `visual-material` |
| 千牛 AI、生意管家、智能体怎么配 | `toolchain-ai` |
| 禁用词、资质、处罚风险 | `compliance-medical` |
| 要开一款新品、趋势词怎么找 | `trend-keyword-launch` |
| 差评里藏着什么需求 | `review-insight-mining` |

完整版见 [`docs/使用说明书.md`](docs/使用说明书.md)。

### 4 · 只想当资料查

每本都有 `cheatsheet.md`（一页决策速查）和 `glossary.md`（术语表，标注来源笔记），让 agent 直接读这两个文件就能拿到最密的信息。

---

## 技能清单

四层共 **20 个** skill，全部已制作并通过质量门禁。

### L0 · 总纲层（1）

| Skill | 用途 |
|---|---|
| [`taobao-ops-playbook`](skills/taobao-ops-playbook/) | 全链路导航与总纲：环境变化、四大金刚、15 条核心公式、爆款四阶段、选路决策树 |

### L1 · 体系层（8 · 跨模块核心方法论）

| Skill | 用途 |
|---|---|
| [`store-diagnosis`](skills/store-diagnosis/) | 店铺经营诊断：领先率四档阈值、四层分析法、归因切换法 |
| [`sabc-product-tiering`](skills/sabc-product-tiering/) | 货盘分级与资源分配：S/A/B/C 判定、预算比例、动态调级 |
| [`wanxiangtai-wujie`](skills/wanxiangtai-wujie/) | 万相台无界投放：成交机会公式、多品多域、P1-P4 方法论 |
| [`hit-product-lifecycle`](skills/hit-product-lifecycle/) | 爆款全生命周期：四阶段、LQ/BQ/CQ、叠标体系 |
| [`customer-asset-ops`](skills/customer-asset-ops/) | 人群资产运营：AIPL/O-AIPL/RFM、召回与复购 |
| [`profit-model`](skills/profit-model/) | 盈利体系与算账：盈亏平衡 ROI、斩杀线、顺逆差、投产去伪 |
| [`daily-store-patrol`](skills/daily-store-patrol/) | **每日巡店（数据驱动）**：连 PG 库逐日体检全店 —— 红绿灯表、异动规则库 28 条、重点商品/计划名单、**可直接跑的巡店脚本** |
| [`domain-growth-ops`](skills/domain-growth-ops/) | **全域增长操盘（决策层）**：智篆商业·老草方法论 —— 推广红绿灯两轴三色与四场景、费比三口径与系列化核算、人群资产分层、系列看板赛马、Gap 公式、左侧拉新两步验证 |

### L2 · 域层（9 · 单业务域专项）

| Skill | 用途 |
|---|---|
| [`selection-testing`](skills/selection-testing/) | 选品与测款：七维选品、五大选款法、虚假爆款识别、测图判据、老草测款方法（共鸣词包 / 点击单价进攻 / 相同流量环境） |
| [`keyword-promo`](skills/keyword-promo/) | 关键词与搜索推广：十三式战法、大词/精准词/长尾词分层、竞品截流 |
| [`conversion-optimization`](skills/conversion-optimization/) | 转化与客单：决策链路优先级、SKU 五要素、FABE 主图、买家秀五法 |
| [`pricing-margin`](skills/pricing-margin/) | 定价与费比：科学定价、预留空间公式、最低价管控、费比核算 |
| [`campaign-playbook`](skills/campaign-playbook/) | 大促作战：六大 S 级大促节奏、报名四要点、蓄水与付费节奏、价盘管控、**双11 备战 2026**（资产召回 / 一品多链 / SKU 独立展示） |
| [`data-metrics`](skills/data-metrics/) | 指标口径与考核维度：四大金刚、8 维度考核、建模路线 |
| [`visual-material`](skills/visual-material/) | 视觉与素材：素材革命八大入口、每周素材 SOP、主图裂变、AI 主图四法 |
| [`toolchain-ai`](skills/toolchain-ai/) | 工具链与 AI 提效：千牛 AI/生意管家三层架构、1 店长+6 数字员工、智能体与多 Agent 配置 |
| [`compliance-medical`](skills/compliance-medical/) | 医疗器械合规红线：禁用词全表、处罚分级、巡检 SOP |

### L3 · 工具层（2 · 可直接跑的技能包）

| Skill | 用途 |
|---|---|
| [`trend-keyword-launch`](skills/trend-keyword-launch/) | 趋势词开款引擎：10 步开款流程、词语 7 分类、词包分层、SAB 分级、表格化输出 |
| [`review-insight-mining`](skills/review-insight-mining/) | 评价挖掘与需求洞察：12 Prompt 链、评价 5 分级、需求地图、冲突点挖掘 |

---

## 一本技能长什么样

```
skills/<skill-name>/
├── SKILL.md      核心框架 + 章节索引 + 主题索引（最关键的内容前置）
├── chapters/     分主题深读文档，按需加载
├── glossary.md   术语表，每条标注来源笔记
├── patterns.md   可复用方法：何时用 / 怎么做 / 代价与风险
├── cheatsheet.md 决策速查：阈值表、决策树、判据、陷阱
└── scripts/      可执行脚本（可选）
```

**为什么这样分**

- `SKILL.md` 永远前置 —— 上下文压缩从尾部截断，最重要的内容不能放最后
- 细节进 `chapters/` 按需加载，不占常驻预算
- `cheatsheet.md` 是决策辅助而不是术语表 —— 术语查 `glossary.md` 就行
- `patterns.md` 强制写明代价，让 agent 知道什么时候**不该**用这个方法

`SKILL.md` 的 frontmatter 只有两个字段，遵循 Anthropic Agent Skills 开放格式：

```yaml
---
name: daily-store-patrol     # 必须与目录名一致
description: "淘宝/天猫店铺每日巡店：……关键词：每日巡店、巡店、红绿灯、费比异常、投产异常……"
---
```

---

## 数据来源与可信度

所有内容来自 `taobao-operation` Obsidian 知识库（2112 篇 / 49MB），经 GBRain 导入（2013 页 / 24077 片段）后逐条编译；数据侧结论来自本机 PostgreSQL 实测（`taobao` 库店铺侧 + `erp` 库交易成本侧，7 个淘宝店铺）。

**编写纪律**

- 数字必须来自知识库原文或数据库实测，**不凭空补全**
- 保留原始专名（`汉堡包计划`、`尖刀连`、`3384 利润公式`、`领先率`、`多品多域`…），不意译
- 素材互相矛盾时**显式标注「口径冲突，需复核」**，不私自选一个
- 无法验证的内容标注「未验证」
- 数据库查询的字段名先对 `information_schema` 核过，查询失败必须可区分于"无数据"

**时效性**：阈值是 2026 上半年口径快照。平台规则会变 —— **落地前核对当期平台公告**。

详见 [`docs/SOURCE-NOTES.md`](docs/SOURCE-NOTES.md)。

---

## 项目结构

```
skill-ecommercial/
├── skills/                    # 20 本技能（每本一个目录）
├── scripts/
│   ├── validate_skills.py     # 质量门禁：10 项检查
│   ├── install_skills.py      # 安装脚本：自动识别宿主目录
│   └── verify_install.py      # 安装验收：逐文件 SHA256 比对仓库与宿主
├── docs/
│   ├── 安装指南.md            # 装到哪、怎么装、怎么调、常见问题
│   ├── 使用说明书.md          # 面向使用者的非技术说明
│   ├── 技能地图.html          # 可视化技能地图
│   ├── ROADMAP.md             # 四层架构与制作批次
│   └── SOURCE-NOTES.md        # 来源与可信度
├── .claude-plugin/            # Claude Code 插件市场清单
├── .github/workflows/         # CI：每次提交跑质量门禁
└── LICENSE                    # MIT
```

---

## 质量保障

`scripts/validate_skills.py` 对全部 20 本跑 10 项检查，CI 每次提交自动执行：

1. 目录结构完整性
2. frontmatter 合法性，`name` 与目录名一致
3. `description` 单行且足够触发
4. `SKILL.md` 正文 token 预算（默认 4000）
5. 无占位符残留（TODO / TBD / 待补充 / FIXME / lorem）
6. 章节非空且不过大
7. `cheatsheet.md` 具决策性（决策标记 + 表格），不是术语罗列
8. `glossary.md` 条目数与来源标注
9. `patterns.md` 的「何时用 / 代价」格式
10. 交叉引用指向真实存在的 skill

```bash
python scripts/validate_skills.py --root .
# 检查 20 个 skill：0 error / 0 warn
```

**装完还能再验一次** —— `scripts/verify_install.py` 逐文件比 SHA256，确认宿主里的内容与仓库完全一致（挡住"文件在但内容是旧版"）：

```bash
python scripts/verify_install.py
# ✅ 验收通过：2 个宿主、20 本技能，文件与仓库一致、frontmatter 均为 name+description
```

---

## 文档索引

| 文档 | 适合谁读 |
|---|---|
| [`docs/安装指南.md`](docs/安装指南.md) | 要装的人 —— 各宿主目录、4 种安装方式、5 种调用方式、常见问题 |
| [`docs/使用说明书.md`](docs/使用说明书.md) | 要用的人 —— 非技术语言的分工说明、症状速查表、一分钟速查 |
| [`docs/技能地图.html`](docs/技能地图.html) | 想知道全貌的人 —— 可视化四层架构（浏览器直接打开） |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 关心设计的人 —— 四层架构、20 本的完整规划、制作批次、已知缺口 |
| [`docs/SOURCE-NOTES.md`](docs/SOURCE-NOTES.md) | 关心可信度的人 —— 来源、纪律、验证记录 |

---

## 路线图与边界

**已覆盖**（知识库 10 大业务模块的笔记数，实测）：

| 模块 | 笔记数 | 落到哪本 |
|---|---|---|
| 95-团队与方法论 | 233 | `taobao-ops-playbook`、`domain-growth-ops`、`store-diagnosis`、`toolchain-ai` |
| 30-流量与推广 | 139 | `wanxiangtai-wujie`、`keyword-promo`、`domain-growth-ops` |
| 20-选品与商品 | 32 | `selection-testing`、`sabc-product-tiering`、`hit-product-lifecycle` |
| 10-战略与商业模式 | 27 | `taobao-ops-playbook`、`profit-model` |
| 70-数据与诊断 | 19 | `data-metrics`、`store-diagnosis`、`daily-store-patrol` |
| 50-客户与私域 | 13 | `customer-asset-ops` |
| 80-店铺后台与工具 | 12 | `toolchain-ai` |
| 60-活动与大促 | 11 | `campaign-playbook` |
| 90-平台规则与合规 | 10 | `compliance-medical` |
| **40-转化与客单** | **4** | `conversion-optimization` —— **全库最稀疏模块，该技能相对单薄，是下一批补强的重点** |

**边界**

- **只覆盖淘系**（淘宝 / 天猫）。京东、拼多多、抖音的对应方法论在知识库中另有笔记，尚未 skill 化
- **医疗器械相关内容仅适用于医疗器械类目**（`compliance-medical`）
- **ERP 商品编码 ↔ 万相台宝贝ID 两套编码尚未对齐**，潜力品识别只能人工映射，已在技能中标注「未验证」
- 阈值是 2026 上半年快照，**落地前核对当期平台公告**
- **大促规则按年份标注**：方法论章（`campaign-playbook` ch06，双11 备战 2026）是 2026 口径；官方报名与价格管控章（ch07）是 **2024/2025 口径**，日期与阈值需回千牛后台当期公告核对

**后续可补**（按优先级）

1. **40-转化与客单模块补强** —— 该模块仅 4 篇、3 篇尚未覆盖，`conversion-optimization` 是当前最薄的一本
2. **2026 双11 官方规则入库** —— 现有官方规则是 2024/2025 快照，当年的招商公告需要从平台侧补
3. **医疗器械四品类打法** —— 家用 / 中医器械 / 医用敷料 / 器械电商，库内均为概念 stub
4. **关键词十三式后 8 式** —— 素材只完整提取到第 5 式，后 8 式无可引用正文
5. **618 项目级复盘闭环 / 新店启动项目** —— 三个项目目录仍是 Phase 4 stub
6. 京东 / 拼多多 / 抖音对应技能、更多行业类目合规包、趋势词开款与评价挖掘的自动化脚本

---

## 常见问题

**Q：装完 `/skill-name` 说找不到？**
A：没重启宿主。技能目录在会话启动时扫描。

**Q：Claude Code 装插件后说找不到技能？**
A：多半是用 URL 直链加的市场。要用 Git 方式：`/plugin marketplace add kizemo/skill-ecommercial`。

**Q：Windows 提示权限不足？**
A：符号链接需要管理员权限。加 `--copy`（skills CLI）或用默认的复制模式（仓库脚本）。

**Q：我没有 PostgreSQL，能用吗？**
A：能。20 本里只有 `daily-store-patrol` 需要数据库，其余 19 本是纯方法论。

**Q：能只装其中几本吗？**
A：能。`npx skills add <repo> -s 'daily-store-patrol,store-diagnosis'`，或用仓库脚本的 `--only`。

**Q：装在哪？C 盘还是 E 盘？**
A：跑 `python scripts/install_skills.py --list-hosts`，看 ★ 标记 —— 那是脚本实际会写的位置。同一台机器上可能同时存在多个配置根，其中一个是符号链接或空壳。

**Q：仓库更新了，已装的宿主怎么同步？**
A：重跑安装脚本并加 `--force`，**装过的每个宿主都要跑一遍**：

```bash
python scripts/install_skills.py --host claude  --force
python scripts/install_skills.py --host minimax --force
```

然后**重启宿主**。校验两侧是否与仓库一致：

```bash
python scripts/verify_install.py          # 全部宿主
python scripts/verify_install.py minimax # 只查 MiniMax Code
```

它会逐文件比对 **SHA256**（不只是文件名），所以"仓库更新了但没重装"这种**旧版内容残留**也能被抓出来。

**Q：双11 那本里的报名截止时间是 2026 的吗？**
A：分两章看 —— **ch06 是 2026 口径**（方法论：资产召回、一品多链、10/15-11/14 窗口）；**ch07 是 2024/2025 官方口径**（报名截止、先涨后降阈值、达摩盘活动）。官方规则**按年发布**，ch07 的日期不能直接用，落地前回千牛后台当期公告核对。

---

## 参与贡献

**加一本新技能**

1. 建目录 `skills/<skill-name>/`，放 `SKILL.md` + `chapters/` + `glossary.md` + `patterns.md` + `cheatsheet.md`
2. `SKILL.md` 的 frontmatter 只写 `name` 和 `description`，`name` 与目录名一致
3. `description` 写成「什么时候用 + 覆盖什么 + 触发关键词」的单行
4. 重要内容前置，控制在 4000 tokens 内
5. 跑 `python scripts/validate_skills.py --root .` 直到 0 error / 0 warn
6. 提 PR

**改内容**

- 数字必须能追到来源（知识库原文或数据库实测）
- 素材冲突标「口径冲突，需复核」，缺失标「未验证」
- 交叉引用用 `[[skill-name]]`

CI 会在每次 push 时跑门禁，不过门禁不会合。

---

## License

MIT —— 见 [LICENSE](LICENSE)。

> ⚠️ 内容为知识库内容的**结构化编译与再表达**，非原文复制。原始知识库含第三方培训内容（如智篆商业系列课程），使用者需自行确认相应内容的再分发授权。

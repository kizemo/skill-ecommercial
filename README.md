# skill-ecommercial

> 淘宝/天猫电商运营 Agent Skills —— 把一套 2013 页的电商运营知识库编译成 agent 可执行的技能。

[![skills](https://img.shields.io/badge/skills-18-blue)](skills/)
[![layer](https://img.shields.io/badge/layer-L0%E2%86%92L3-green)](docs/ROADMAP.md)
[![source](https://img.shields.io/badge/source-taobao--operation-orange)](docs/SOURCE-NOTES.md)

---

## 这是什么

一个把**电商运营方法论**装进 agent 的技能库。覆盖从选品、测款、推广、转化、客户到数据诊断、大促作战、合规红线的完整链路。

不是"文档摘要"，是**可执行的决策工具**：每个 skill 给的是框架名、步骤、判断标准、具体阈值和踩坑清单 —— 让 agent 能回答"我现在该做什么、依据是什么、什么时候停"。

## 快速开始

```bash
# 在任意支持 Agent Skills 的宿主上安装
npx skills add https://github.com/kizemo/skill-ecommercial
```

或直接克隆后按宿主规则放入技能目录：

| 宿主 | 个人级目录 | 项目级目录 |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| OpenCode | `~/.agents/skills/` | `.agents/skills/` |
| Copilot CLI | `~/.agents/skills/` | `.github/skills/` |
| OpenClaw | `${OPENCLAW_STATE_DIR:-~/.openclaw}/skills/` | `skills/` |

`skills/taobao-ops-playbook/` 是总纲入口，**建议第一个装**。

## 技能清单

### L0 · 总纲层

| Skill | 用途 |
|---|---|
| [`taobao-ops-playbook`](skills/taobao-ops-playbook/) | 全链路导航与总纲：环境变化、四大金刚、15 条核心公式、爆款四阶段、选路决策树 |

### L1 · 体系层（跨模块核心方法论）

| Skill | 用途 |
|---|---|
| [`sabc-product-tiering`](skills/sabc-product-tiering/) | 货盘分级与资源分配：S/A/B/C 判定、预算比例、动态调级 |
| [`store-diagnosis`](skills/store-diagnosis/) | 店铺经营诊断：领先率四档阈值、四层分析法、归因切换法 |
| [`wanxiangtai-wujie`](skills/wanxiangtai-wujie/) | 万相台无界投放：成交机会公式、多品多域、P1-P4 方法论 |
| [`hit-product-lifecycle`](skills/hit-product-lifecycle/) | 爆款全生命周期：四阶段、LQ/BQ/CQ、叠标体系 |
| [`customer-asset-ops`](skills/customer-asset-ops/) | 人群资产运营：AIPL/O-AIPL/RFM、召回与复购 |
| [`profit-model`](skills/profit-model/) | 盈利体系与算账：盈亏平衡 ROI、斩杀线、顺逆差、投产去伪 |

### L2 · 域层（单业务域专项）

| Skill | 用途 |
|---|---|
| [`selection-testing`](skills/selection-testing/) | 选品与测款：七维选品、五大选款法、虚假爆款识别、测图判据 |
| [`keyword-promo`](skills/keyword-promo/) | 关键词与搜索推广：十三式战法、大词/精准词/长尾词分层、竞品截流 |
| [`conversion-optimization`](skills/conversion-optimization/) | 转化与客单：决策链路优先级、SKU 五要素、FABE 主图、买家秀五法 |
| [`pricing-margin`](skills/pricing-margin/) | 定价与费比：科学定价、预留空间公式、最低价管控、费比核算 |
| [`campaign-playbook`](skills/campaign-playbook/) | 大促作战：六大 S 级大促节奏、报名四要点、蓄水与付费节奏、价盘管控 |
| [`data-metrics`](skills/data-metrics/) | 指标口径与考核维度：四大金刚、8 维度考核、建模路线 |
| [`visual-material`](skills/visual-material/) | 视觉与素材：素材革命八大入口、每周素材 SOP、主图裂变、AI 主图四法 |
| [`toolchain-ai`](skills/toolchain-ai/) | 工具链与 AI 提效：千牛 AI/生意管家三层架构、1 店长+6 数字员工、AI 巡店与商品诊断、智能体与多 Agent 配置 |
| [`compliance-medical`](skills/compliance-medical/) | 医疗器械合规红线：禁用词全表、处罚分级、巡检 SOP |

### L3 · 工具层（可直接跑的技能包）

| Skill | 用途 |
|---|---|
| [`trend-keyword-launch`](skills/trend-keyword-launch/) | 趋势词开款引擎：10 步开款流程、词语 7 分类、词包分层、SAB 分级、表格化输出 |
| [`review-insight-mining`](skills/review-insight-mining/) | 评价挖掘与需求洞察：12 Prompt 链、评价 5 分级、需求地图、冲突点挖掘 |

> 四层共 **18 个** skill，全部已制作并通过质量门禁。完整规划见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

## 每个 skill 的结构

```
skills/<skill-name>/
├── SKILL.md      核心框架 + 章节索引 + 主题索引（最关键的内容前置）
├── chapters/     分主题深读文档，按需加载
├── glossary.md   术语表，每条标注来源笔记
├── patterns.md   可复用方法：何时用 / 怎么做 / 代价与风险
└── cheatsheet.md 决策速查：阈值表、决策树、判据、陷阱
```

**为什么这样分**：`SKILL.md` 永远前置（上下文压缩从尾部截断，最重要的内容不能放最后）；细节进 `chapters/` 按需加载，不占常驻预算；`cheatsheet.md` 是决策辅助而不是术语表 —— 术语查 `glossary.md` 就行。

## 内容来源与可信度

所有内容来自 `taobao-operation` Obsidian 知识库（2112 篇 / 49MB），经 GBRain 导入（2013 页）后逐条编译。

**编写纪律**：
- 数字必须来自知识库原文，**不凭空补全**
- 保留原始专名（`汉堡包计划`、`3384 利润公式`、`领先率`、`多品多域`…），不意译
- 素材互相矛盾时**显式标注「口径冲突，需复核」**，不私自选一个
- 无法验证的内容标注「未验证」

**时效性**：阈值是 2026 上半年口径快照。平台规则会变 —— **落地前核对当期平台公告**。

详见 [`docs/SOURCE-NOTES.md`](docs/SOURCE-NOTES.md)。

## 规划与边界

- [`docs/使用说明书.md`](docs/使用说明书.md) —— **面向使用者的完整说明书**（分工 / 调用方式 / 症状速查），配套可视化页 [`docs/技能地图.html`](docs/技能地图.html)
- [`docs/ROADMAP.md`](docs/ROADMAP.md) —— 四层架构、18 个 skill 的完整规划、制作批次、质量门禁、已知缺口
- **只覆盖淘系**（淘宝/天猫）。京东 / 拼多多 / 抖音的对应方法论在知识库中另有笔记，本轮未 skill 化
- 医疗器械相关内容仅适用于医疗器械类目

## License

MIT —— 见 [LICENSE](LICENSE)。

> ⚠️ 内容为知识库内容的**结构化编译与再表达**，非原文复制。原始知识库含第三方培训内容（如智篆商业系列课程），使用者需自行确认相应内容的再分发授权。

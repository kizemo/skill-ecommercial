# skill-forge 审计报告 · skill-ecommercial

> **运行日期**：2026-10-26 ｜ **工具**：`skill-forge` v0.2.0（`F:\soft\00selfmade\skill-optimizer\skill-forge`）
> **目标技能**：[`skills/skill-ecommercial/`](../../skills/skill-ecommercial/)（L0 总纲入口）
> **范围**：`--scope improve`，`--held-out 15`，`--split 1:1:1`，`--max-usd 5.00`，隔离 `GBRAIN_HOME`
> **最终退出码**：`0`（accept）

---

## 一、三裁判结论

skill-forge 的 verify 阶段有三个独立裁判，缺一个就失去一种失效模式的覆盖。三裁判都列在这里，含**未运行的那一格**。

| 裁判 | 问的问题 | 本次结果 | 怎么做的 |
|---|---|---|---|
| **① 确定性 trace** | 结构对不对（frontmatter 合法、`name` 合规、正文无 `TODO/TBD`） | **pass** | skill-forge 内置 `_deterministic_trace()`。baseline **fail**（description 不以 `Use when` 开头），candidate **pass** |
| **② LLM rubric** | 意图对不对（frontmatter 与正文语义是否匹配） | **skipped（本机无裁判通道）** | 见下方「为什么没跑成」——按 RULING-1，**缺席 ≠ 失败** |
| **③ spot check** | 行为对不对（规则化的可复现验收） | **pass：baseline 9/15 → candidate 15/15** | 本轮自写的规则化检查器，见 [spot-check.md](spot-check.md)。已用**坏技能对照**验过它有牙（6/15） |

> ⚠️ **裁判②没跑成，别把它当已验证。** 本机 `llm-call` 脚本的静态 `apiKey` 是占位符（`sk-x…`，6 字符），
> 真实 token 只在运行中的 app 内刷新、独立脚本刷不出来；环境里也没有 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`
> 可走 HTTP 通道。原始报错：`Error 401: {"code":401,"message":"token is required"}`。
> skill-forge 的 `judge_triple.py` 把这种情况记为 **rubric-skipped**（不是 0 分），符合 RULING-1。
> **裁判③是本轮自写的**——自己写的裁判比自己写的正文更可能同源犯错，所以它同时给出了**逐行判据**和**坏数据对照**，
> 结论请以逐行判据为准，不要只看那个 15/15 的数字。

### Phase 3 前向（gbrain skillopt）实际做了什么

| 项 | 实测值 |
|---|---|
| 路由结果 | `gbrain-skillopt`，`degraded=false`，exit 0 |
| 模式 | `--dry-run`（skill-forge 的 router 写死该标志）→ **未产生任何模型调用** |
| 报价 | 4 epochs × 1 step × 8 rollouts = 117 calls + 12 reflects；~447K in / ~112K out tokens；**估算 $3.01**（上限 $5.00） |
| 需要的模型 | optimizer `anthropic:claude-opus-4-7`、target/judge `anthropic:claude-sonnet-4-6`、expansion `anthropic:claude-haiku-4-5` |
| 本机能否真跑 | **不能**：隔离 `GBRAIN_HOME` 里没有 Anthropic 凭据；且 bootstrap 出的 benchmark 是 `judge.kind="rule"`，gbrain 自报 `Judges: 0 calls` |
| 附带发现 | 隔离 brain 有未应用迁移（`gbrain apply-migrations --yes`）；`embedding` 模型未解析 |

**所以「前向」在本轮的真实作用是取报价与覆盖面诊断，改写正文由作者完成** —— 这也是 skill-forge 自己的分工：
「skill-forge does not write skills. It audits, judges, and materializes. The author still writes the body.」

---

## 二、Cost（两套口径，别混用）

skill-forge 的 `measure_skill()` 按 **CJK 1 字 ≈ 1 token** 估；本仓库门禁按 **CJK 1.6 字 ≈ 1 token** 估。
前者保守、偏英文字面；后者更接近真实分词器。**两个都报，因为两个都是真的约束。**

| 档 | baseline | candidate | skill-forge 预算 | 仓库预算 | 结论 |
|---|---|---|---|---|---|
| **index**（每会话都付） | 214 tok | **100 tok** | ~100 | 无硬上限 | ✅ 从 2.1× 预算降到 1.0× |
| **load**（每次触发付，skill-forge 口径） | 3169 tok | **4723 tok** | ~5000 | 无硬上限 | ✅ 仍在预算内（用掉了 94%） |
| **load**（仓库口径） | 2166 tok | **3180 tok** | — | ≤ 4000（硬门禁） | ✅ 余量 820 tok |
| description 长度 | 230 字符 / 19 个关键词 | **102 字符 / 6 个关键词** | ≤ 1024 字符 / ≤ 50 词 | 单行 | ✅ |
| 正文行数 | 174 | 257 | — | — | +83 行 |
| files 档 | 0 | 0 | 无上限 | — | 入口技能本来就没有 scripts/references |

> **index 是这次最值钱的一处改动。** 它**每一个会话都在付**，不管这本技能有没有被触发；20 本一起装的时候，
> 省下的 114 tok/技能 × 20 = **2280 tok/会话**，是白拿的。

---

## 三、Change（SKILL.md vs 运行前快照）

完整 diff：[`change.diff`](change.diff)（+113 / −27 行）。要点：

| 改动 | 为什么 |
|---|---|
| `description` 换成路由触发器 + 中文关键词子句 | index 214 → 100 tok；把「这个技能做什么」改成「**什么时候该用它**」 |
| 新增开头**铁律**一行 | skill-forge PRINCIPLES § 2.1（Iron Law：一个可覆盖一切的短句） |
| 新增「**何时用 / 何时不用**」表 | § 2.2；也是 description 里那句「任务已明确就直进专项技能」的正文落点 |
| 新增「**七、五步路由流程**」 | § 2.3（编号化工作流）；L0 的产品本来就是流程，原先是散的 |
| 新增「**十、常见误区与红线**」 | § 2.4 / § 2.5；四条「常见推托 + 实情」+ 五条「发现即停」 |
| 新增「**十一、输出格式**」 | § 2.8；原来没说清「用完这本技能该交付什么」，导致回答形态不可控 |
| 新增「**十二、验收**」 | § 2.6；把仓库自己的门禁写进技能里，让模型自己先过一遍 |
| 新增「**十三、读文件条件**」表 | 评分表第 5 行（body 必须声明附件读取条件）；原来只有一列「Supporting Files」平铺清单 |
| 「Supporting Files」平铺清单 → 读文件条件表 | 同上；顺便把章节链接从代码块改成可点链接 |
| 章节重编号（七/八/九…） | 插入新节导致；**§六「诊断入口」编号保持不变**——[ch05-组件编排](../../skills/skill-ecommercial/chapters/ch05-组件编排.md) 里有交叉引用指向它 |
| 「Scope & Limits」→「边界（Scope & Limits）」 | 保留原标题语义，加中文便于检索 |

---

## 四、逐条归因：skill-forge 的发现 vs 本仓库规范

> 仓库惯例：**审计时以仓库规范为准，skill-forge 的结论要逐条归因**（见 `.work/HANDOFF.md` §十第 5 条）。

| skill-forge 的要求 | 本仓库的规范 | 本轮处置 | 理由 |
|---|---|---|---|
| frontmatter 加 `triggers` / `mutating` / `version` / `brain_first` / `when_to_use` | **只允许 `name` + `description`**（`HANDOFF` §二第 5 条明写「优先于 skill-forge 的 `triggers/tools/version` 布局」） | **不加** | ① Anthropic Agent Skills 开放格式只认这两个键，其余键宿主直接忽略 = 纯开销；② 仓库门禁 `selfcheck.py` 会判「frontmatter 多余键」为问题；③ `triggers` 的作用由 description 的关键词子句承担（仓库 20 本一致的做法） |
| `description` 以 `Use when` / `Load when` 开头 | 中文关键词 description | **采纳，但做成中英混排**：`Use when 淘系运营…关键词：运营总纲、运营手册、GSV。L0 路由总纲只定位不执行…` | 工具的确定性 trace 与 rubric 都硬性要求这个前缀；它同时是给 resolver 的机器可读信号，代价 3 个 token，且**不破坏中文关键词机制**（关键词子句仍在，宿主照旧靠它匹配） |
| `description` ≤ 50 词、**不要关键词堆砌** | 关键词是触发器（`docs/安装指南.md` 明写「description 里那一串关键词就是自动触发器」） | **两个都满足**：关键词从 **19 个减到 6 个**（枚举项 19 → 6，低于「堆砌」判定阈值 10），保留的 6 个是 L0 自己独占的意图词 | 「运营总纲 / 运营手册 / GSV」是用户对这本技能的真实叫法；「店铺诊断 / 货盘分级 / 爆款阶段 / 选品测款」**故意不给**——那些是 `store-diagnosis` / `sabc-product-tiering` / `hit-product-lifecycle` / `selection-testing` 的地盘，抢它们会违反 PRINCIPLES § 6 的 MECE |
| body ≤ ~5000 token | ≤ 4000（仓库口径，硬门禁） | **两套都过**（4723 / 3180） | — |
| body 要有 `## Common Rationalizations` / `## Red Flags` / `## Anti-Patterns` | 仓库没有这个强制项 | **采纳**，做成中英混排小节名「常见误区与红线（Common Rationalizations / Red Flags）」 | 工具的 rubric 明确看「body 有没有 gotcha 段」；混排让中文读者可读、让工具的正则也认得 |
| body 要声明附件读取条件 | 仓库没有强制项 | **采纳**：新增「十三、读文件条件」表 | 评分表第 5 行。原来的「Supporting Files」只列了文件，读的人不知道**什么时候该读**——这正是渐进式披露（PRINCIPLES § 3）要解决的事 |
| 条件性内容放 `references/` | 本仓库用 `chapters/` + 三件套 | **不改目录结构** | `chapters/` 就是本仓库版的 spoke，`SKILL.md` 是 hub。评分表第 7 行的启发式只认 `references/` / `assets/` 目录名，是工具的目录名假设，不是质量判断 |
| `audit.py` 的 root cause 分类 | — | 本轮 candidate 判成 `other` → 推荐 `audit-only` | **这是工具的分类器缺口，不是技能的缺陷**：它的分支只有 `routing` / `prompt` / `contract` / `missing` / `other`，**没有「健康」这一档**——描述合规、正文够长、脚本没坏，四个分支全不匹配就落到 `other`。baseline 判成 `routing`（描述不以 `Use when` 开头）才是真的命中 |
| Phase 3 前向要真跑 gbrain | — | **未真跑**（dry-run） | 真跑要 Anthropic 凭据，本机没有；报价 $3.01 已记录在案。skill-forge 的分工本来就是「作者写正文」 |

---

## 五、本轮改了什么、没改什么

### 改了（8 项，全部在 `skills/skill-ecommercial/SKILL.md`）

1. `description` 重写：路由前缀 + 6 个关键词 + 「只定位不执行」的差异化声明。
2. 开头加**铁律**一行（定位 → 取阈 → 动作）。
3. 新增「何时用 / 何时不用」表（含 5 条「不用」，各自给了去处）。
4. 新增「五步路由流程」（定位 / 取数 / 取阈 / 选路 / 执行，每步带落点）。
5. 新增「常见误区与红线」（4 条常见推托 + 5 条发现即停）。
6. 新增「输出格式」（四行固定格式 + 推广红绿灯的附加要求）。
7. 新增「验收」（6 条自查项，与仓库门禁同口径）。
8. 「Supporting Files」平铺清单 → 「读文件条件」表（文件 / 什么时候读 / 不读会怎样）。

### 没改（有意不动）

- **frontmatter 的键集合**：维持 `name` + `description`（理由见第四节）。
- **`chapters/`、`glossary.md`、`patterns.md`、`cheatsheet.md`**：本轮只优化入口正文，三件套与 5 个分册**逐字节未动**。
- **§六「诊断入口」的编号**：保持不变，避免打断 [ch05-组件编排](../../skills/skill-ecommercial/chapters/ch05-组件编排.md) 的交叉引用。
- **正文里的每一个数字与阈值**：本轮**没有增删任何一个数字**。所有原有阈值（GSV、领先率分档、SABC 预算占比、四阶段天数等）原样保留；新增内容不含未溯源的数字。仓库的「数字纪律」不受本轮影响。

### 未验证 / 已知边界

- **LLM rubric 未跑**（见第一节）。「candidate 意图是否真的更好」这句话目前只有规则化裁判 + 作者自评背书，**没有独立模型背书**。
- **无路由回归测试**：本次没有「正例提问应当命中 / 负例提问不应命中」的 hero-query 集。skill-forge 的 Phase 2 bootstrap 生成的 15 行 benchmark 是**模板行**（见 [`benchmark.jsonl`](benchmark.jsonl)），不是真实用户提问，**不能当路由评测集用**。
- **关键词裁剪的路由影响未实测**：把 19 个关键词减到 6 个，理论上更符合「index 预算」与 MECE，但**实际召回率变化没有测过**。若后续发现「怎么诊断店铺」这类问法不再命中 L0，按补回关键词处理（补回时先确认不与 `store-diagnosis` 抢意图）。
- **gbrain 前向未真跑**：报价与模型需求已记录，没有真实优化轨迹可比。

---

## 六、复现

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='F:\soft\00selfmade\skill-optimizer\skill-forge'
cd 'F:\soft\00selfmade\skill-ecommercial'

# 1) 装一份 scratch 副本（不要在 skills/ 里直接跑，skill-forge 会往技能目录写 audit-report.md / best.md）
# 2) 预置真 baseline 快照（skill-forge 的 snapshot 不覆盖已有快照，预置后 Phase 4 才有 before/after）
# 3) 跑六阶段
python -m scripts --skill <scratch>\skill-ecommercial --scope improve --held-out 15 --spot-check 1

# 4) 规则化 spot check（baseline vs candidate）
python .work\skill-forge-run\spot_check.py skills\skill-ecommercial .work\skill-forge-run\baseline\skill-ecommercial

# 5) 造坏技能，验 spot check 有牙
python .work\skill-forge-run\_mkbroken.py
python .work\skill-forge-run\spot_check.py .work\skill-forge-run\broken-ecommercial
```

> `scripts/`、`references/`、`assets/` 三档成本里，本技能 `files` 档为 0 —— 它是纯路由入口，没有脚本；
> 真正的脚本在 `domain-growth-ops/scripts/red_green_report.py`，按需才读。

---

## 相关

- 本目录说明与判据口径：[README.md](README.md)
- 规则化 spot check 逐行判据与坏数据对照：[spot-check.md](spot-check.md)
- Phase 2 bootstrap 的 15 行 benchmark：[`benchmark.jsonl`](benchmark.jsonl)
- 完整改动 diff：[`change.diff`](change.diff)

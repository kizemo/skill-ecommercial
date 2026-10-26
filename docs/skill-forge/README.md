# skill-forge 审计留痕

> 本目录是 **skill-forge**（`F:\soft\00selfmade\skill-optimizer\skill-forge`，v0.2.0）在本仓库的运行留痕。
> 目的：让「这个技能被优化过、依据是什么、哪些结论没验」可被任何人复核，而不是一句「优化完了」。

## 目录里有什么

| 文件 | 内容 |
|---|---|
| [`audit-report.md`](audit-report.md) | **正式审计报告**：三裁判结论（含未运行的那一格）、Cost（两套口径）、Change 摘要、**逐条归因**、改了什么/没改什么、未验证清单、复现步骤 |
| [`spot-check.md`](spot-check.md) | 规则化 spot check 的**逐行判据**与结果，以及**坏数据对照**（证明检查器有牙） |
| [`change.diff`](change.diff) | `SKILL.md` 的完整 diff（+113 / −27 行） |
| [`benchmark.jsonl`](benchmark.jsonl) | Phase 2 bootstrap 生成的 15 行 benchmark（模板行，**不是**路由评测集） |

## 三条读这份留痕前要知道的事

1. **仓库规范优先于工具规范。** 本仓库的 frontmatter 只允许 `name` + `description`
   （`.work/HANDOFF.md` §二第 5 条已明写「优先于 skill-forge 的 `triggers/tools/version` 布局」）。
   skill-forge 的每一条建议都在 [audit-report.md](audit-report.md) 第四节做了**逐条归因**：采纳、折中、还是不改，各有理由。

2. **有一格裁判没跑成。** LLM rubric 因本机没有可用的裁判通道而 **skipped**（按 RULING-1，缺席 ≠ 失败）。
   证据（401 原文）、以及为什么没有别的通道，都在 [audit-report.md](audit-report.md) 第一节。
   **别把「三裁判通过」当成已验证**——实际是「两裁判通过 + 一裁判缺席」。

3. **spot check 是本轮自写的。** 自己写的裁判更容易和正文同源犯错，所以它给了**逐行判据**和**坏数据对照**，
   结论请以逐行判据为准，不要只看那个 15/15 的数字。

## 这轮优化了什么（一句话版）

`skill-ecommercial`（L0 总纲入口）的 `description` 从「自我介绍式关键词堆砌」改成「路由触发器」，
index 档 **214 → 100 token**（这一档每个会话都付）；正文补上铁律、路由流程、常见误区与红线、
输出格式、验收清单、读文件条件六块，load 档 4723 token（预算 ~5000），仓库硬门禁口径 3180 token（上限 4000）。

**没有增删任何一个阈值数字**，没有动 `chapters/`、三件套和其他 19 本技能。

## 为什么留在这个目录

- skill-forge 自己的规矩：**「Skip Phase 5 to ship faster → No materialize, no run.」** 不落材料，这次运行就不算数。
- 公开仓库的好处就是可复核：别人能拿着 diff 和判据重跑一遍，而不是只能相信作者。
- 数字纪律要求「每个阈值都能指到出处」——同理，**每个「优化过了」的结论也得能指到判据**。

## 复现

见 [audit-report.md](audit-report.md) 第六节。检查器与坏数据脚本在 `.work/skill-forge-run/`（gitignored，不进仓库）。

# 规则化 spot check · skill-ecommercial

> 这是 skill-forge 三裁判里的**第三格**（行为/验收裁判）。第一格是确定性 trace（内置），
> 第二格是 LLM rubric（本机无裁判通道，**skipped**——详见 [audit-report.md](audit-report.md) 第一节）。
> 既然第二格跑不了，第三格必须给出真货，否则整条流水线就只剩一个裁判。

## 判据从哪来

- skill-forge `docs/SKILL-DESIGN-GUIDE.md` → *The scoring sheet*：**前 7 行标注为 `Automated? = yes`**，那是被工具认定为「真正管住 token 成本」的那一半。
- skill-forge `docs/PRINCIPLES.md` § 1（frontmatter）/ § 2（正文结构）。
- 再叠一层**本仓库自己的权威门禁**口径（`scripts/validate_skills.py` + `.work/selfcheck.py`）——
  因为本仓库的硬门禁与 skill-forge 的并不完全重合，两边都要过。

**15 行 = skill-forge 7 行 + 仓库 8 行。** 每一行都是能复算的二元判定，没有主观打分。

## 逐行判据

| # | 检查项 | 判据 | 来源 |
|---|---|---|---|
| 1 | index ≤ 100 tok | frontmatter 渲染后的 token 估算 ≤ 100 | 评分表 1 |
| 2 | description 合规 | 以 `Use when`/`Load when` 开头 + ≤ 50 词 + 枚举项 ≤ 10（不是关键词堆砌）+ 含触发条件句 | 评分表 2 |
| 3 | 触发语无重复 | description 里没有重复短语 | 评分表 3 |
| 4 | body ≤ 5000 tok | skill-forge 口径 | 评分表 4 |
| 5 | 有读文件条件 | 正文出现「什么时候读 / Read … if / 读文件条件 / Read Conditions」 | 评分表 5 |
| 6 | 有误区/红线段 | 存在 gotcha 风格小节（Common Rationalizations / Red Flags / Anti-Patterns / 误区 / 红线 / 反模式） | 评分表 6 |
| 7 | 条件内容外置 | 存在 `chapters/` 或 `references/` 目录 | 评分表 7（本仓库用 `chapters/`） |
| 8 | frontmatter 仅 name+description | 无多余键 | 仓库门禁 |
| 9 | name == 目录名 | 严格相等 | 仓库门禁 |
| 10 | body ≤ 4000 tok（仓库口径 CJK/1.6） | ≤ 4000 | 仓库门禁（硬） |
| 11 | 无占位符 | 无 `TODO`/`TBD`/`FIXME`/`XXX`/`待补充`/`占位符`/`lorem ipsum` 等 | 仓库门禁 |
| 12 | 相对链接无死链 | 技能目录内所有 `](xxx.md)` 都能落到真实文件 | 仓库门禁 |
| 13 | `[[skill]]` 全部存在 | 交叉引用的技能目录真实存在 | 仓库门禁 |
| 14 | 有输出格式段 | 正文出现「输出格式 / Output Format」小节 | skill-forge PRINCIPLES § 2.8 |
| 15 | 有验收清单段 | 正文出现「验收 / 自查 / Verification」小节 | skill-forge PRINCIPLES § 2.6 |

> 第 2 行的「堆砌」判定阈值取 **10**：skill-forge 原文说「2-3 个例子通常覆盖 80/20，不是关键词堆砌」。
> 要把这句话变成可复算的二元判定，就得给「堆砌」一个数。baseline 的枚举项是 **19**，candidate 是 **6**，
> 阈值取 10 能干净地把两者分开，且中间留了余量。

## 结果

```
| # | 检查项                                    | baseline | candidate | 说明（candidate）                    |
|---|-------------------------------------------|----------|-----------|---------------------------------------|
| 1 | index ≤100tok                             | ❌ 214   | ✅ 100    | 214 → 100                            |
| 2 | desc 路由前缀/≤50词/非堆砌/含条件句        | ❌        | ✅        | 4 词，前缀=True，枚举 6 项，条件句=True |
| 3 | 触发语无重复                               | ✅        | ✅        | 重复 0 处                            |
| 4 | body ≤5000tok（skill-forge 口径）          | ✅ 3169   | ✅ 4723   |                                        |
| 5 | 有读文件条件                               | ❌        | ✅        | 新增「十三、读文件条件」表            |
| 6 | 有误区/红线段                              | ❌        | ✅        | 新增「十、常见误区与红线」            |
| 7 | 条件内容外置                               | ✅        | ✅        | chapters/                             |
| 8 | frontmatter 仅 name+description           | ✅        | ✅        | 多余键：无                            |
| 9 | name==目录名                              | ✅        | ✅        | skill-ecommercial                     |
| 10| body ≤4000tok（仓库口径）                  | ✅ 2166   | ✅ 3180   | 余量 820                             |
| 11| 无占位符                                   | ✅        | ✅        | 命中：无                              |
| 12| 相对链接无死链                             | ✅        | ✅        | 0 条                                  |
| 13| [[skill]] 全部存在                        | ✅        | ✅        | 缺失：无                              |
| 14| 有输出格式段                               | ❌        | ✅        | 新增「十一、输出格式」                |
| 15| 有验收清单段                               | ❌        | ✅        | 新增「十二、验收」                    |

baseline:  9/15 通过
candidate: 15/15 通过      净增 6 项
```

## 这个检查器有牙吗？—— 有，验过了

**全绿不能证明检查器在检查。** 一个永远返回通过的检查器和一个真在检查的检查器，输出长得一模一样。
所以按仓库纪律，**造了一份坏技能去对照**：往副本里逐条注入 9 处缺陷，看检查器是不是**逐条**报出来。

注入的缺陷与期望挂掉的行：

| 注入的缺陷 | 期望挂掉 | 实测 |
|---|---|---|
| description 去掉 `Use when` 前缀 + 塞 16 项关键词 | 第 2 行 | ✅ 报「前缀=False, 枚举16项(堆砌=True), 条件句=False」 |
| 关键词重复 15 次 | 第 3 行 | ✅ 报「重复 15 处」 |
| 删掉读文件条件表 | 第 5 行 | ✅ 报「缺读取条件」 |
| 删掉误区/红线段 | 第 6 行 | ✅ 报「无」 |
| frontmatter 加 `triggers` / `mutating` | 第 8 行 | ✅ 报「多余键 ['triggers', 'mutating']」 |
| 正文塞 `TODO: 待补充…` | 第 11 行 | ✅ 报「命中 ['TODO', '待补充']」 |
| 把 ch02 链接改成 `ch99-不存在.md` | 第 12 行 | ✅ 报「1 条死链」 |
| 删掉输出格式段 | 第 14 行 | ✅ 报「无」 |
| 删掉验收清单段 | 第 15 行 | ✅ 报「无」 |

坏技能实测 **6/15 通过** —— 9 处注入缺陷**一处不漏**全部被逐条报出，没有漏报也没有多报。

> 第 9 行（name == 目录名）在坏技能对照里是「通过」的：注入脚本把 name 一并改成了与目录名一致，
> 以免这一行和第 8 行重复报同一处。它的判别力是在 baseline 阶段验的——baseline 目录当时叫
> `baseline-ecommercial`，这一行立刻报 ❌。**两行覆盖的是不同的缺陷。**

## 复现

```powershell
$env:PYTHONIOENCODING='utf-8'
cd 'F:\soft\00selfmade\skill-ecommercial'

# baseline vs candidate
python .work\skill-forge-run\spot_check.py `
  skills\skill-ecommercial `
  .work\skill-forge-run\baseline\skill-ecommercial

# 造坏技能 + 验检查器有牙
python .work\skill-forge-run\_mkbroken.py
python .work\skill-forge-run\spot_check.py .work\skill-forge-run\broken-ecommercial
```

> 检查器与坏数据脚本都放在 `.work/`（gitignored 草稿区），**不进 public 仓库**——
> 它们是本轮的验证工装，不是交付物。要长期跑，把 `spot_check.py` 挪进 `scripts/` 并接到 CI。

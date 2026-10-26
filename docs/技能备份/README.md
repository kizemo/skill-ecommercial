# 技能入口正文备份

> 这不是**副本**，不是权威版本。权威版本在 [`../../skills/`](../../skills/)。
> 两者由 [`scripts/verify_docs_backup.py`](../../scripts/verify_docs_backup.py) 逐字节校验，漂移即 CI 失败。

## 为什么留这份备份

- **不装技能也能读**：在 GitHub 上点开任意一本的入口正文，就能看到它「什么时候用、什么时候别用、输出格式、验收清单」——不用 clone、不用装宿主。
- **入口正文就是路由表**：每本技能的第一屏决定了「这句话该不该落到这本技能上」。这是最该被公开评审的部分。
- **审阅成本低**：改技能时只需先改 `skills/`，再跑一次同步命令，diff 就是入口正文的变化。

## 这里有什么

| 文件 | 内容 | 与权威版的关系 |
|---|---|---|
| `<技能名>/SKILL.md` | 该技能的入口正文（frontmatter + 正文） | 逐字节同源，唯一差别是**相对链接改写成指向 `../../skills/<技能名>/…`** |

**不含** `chapters/`、`glossary.md`、`patterns.md`、`cheatsheet.md`、`scripts/` —— 这些是随读随载的分册，
按需去 [`../../skills/`](../../skills/) 取，备份里不做重复。

## 同步命令

```powershell
# 重新生成（改完 skills/ 之后跑）
python scripts\verify_docs_backup.py --write

# 只校验，不改（CI 跑这个）
python scripts\verify_docs_backup.py
```

> 备份里改内容是无效的——下次 `--write` 会被覆盖。要改就改 `skills/` 下的权威版。

## 链接改写规则

| 原文 | 备份里 |
|---|---|
| `](chapters/ch02-核心公式手册.md)` | `](../../../skills/<技能名>/chapters/ch02-核心公式手册.md)` |
| `](glossary.md)` | `](../../../skills/<技能名>/glossary.md)` |

备份文件在 `docs/技能备份/<技能名>/`，仓库根在**三级**之上，所以前缀是 `../../../skills/`。
`http(s)://` 开头的外链、锚点链接、绝对路径一律保持原样。

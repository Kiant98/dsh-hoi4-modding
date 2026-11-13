# 贡献指南 · Contributing

感谢你愿意花时间。这个工具包的每一条错题、每一篇参考、每一类校验器，都是被真实的模组文件逼出来的——所以最有价值的贡献，通常是你刚踩过的那个坑。

Thanks for taking the time. Every entry in this toolkit was forced by a real mod file. The most valuable contribution is usually the bug you just hit.

## 可以贡献什么 · What you can contribute

| 类型 | 位置 | 说明 |
|---|---|---|
| 错题（Error Book） | `references/91_error-book/` | 一条已实证的踩坑：症状、错误做法、根因、标准化方案。最欢迎的一类 |
| 方案（Solutions） | `references/92_solutions/` | 未验证的解决思路，按状态标注 `upstream-only` / `suspect` / `rejected` / `promoted` |
| 参考文档 | `references/` 各域 | 字段级说明、版本差异、真实写法对比。必须能指到原版文件的行号 |
| 校验器 | `mcp-server/checks.py`、`validators.py` | 新增一类静态检查（三步，见下） |
| 示例模组 | `examples/` | 正例或反例夹具。反例要说明每处缺陷为什么危险 |
| 文档 / 翻译 | 根 `*.md`、`skills/` | 修正错误、补例子、改进英文表达 |
| 缺陷报告 | GitHub Issues | 带上 `error.log` 片段、模组片段、复现命令 |

**不收**：游戏素材（版权）、第三方模组整包、无法指出来源的经验之谈、纯「优化一下代码风格」的改动。

## 快速上手 · Quick start

```bash
git clone https://github.com/Kiant98/dsh-hoi4-modding.git
cd dsh-hoi4-modding
python mcp-server/selftest.py          # 368 项断言，必须全绿
python mcp-server/server.py --list     # 20 个工具
python mcp-server/server.py --call kiant_hoi4_validate_mod '{"mod_path":"examples/broken_mod"}'
```

需要 Python 3.9+，只用标准库。不需要游戏本体就能跑自检；只有跑知识库索引和 `self_check` 才需要游戏目录。

## 硬性要求 · Hard requirements

1. **`python mcp-server/selftest.py` 必须全绿**（当前 368 项）。改了校验器、解析器、文档数字，都得先跑它。
2. **文档里的数字必须与代码一致**。自检会跨 6 份文档核对「N 个技能 / N 个工具 / N 篇文档 / N 条错题本 / 自检项数」，写错就红。
3. **工具、技能、脚本一律 `kiant-` / `kiant_hoi4_` 前缀**。自检会拦下旧的无前缀路径。
4. **本地化文件必须 UTF-8 with BOM**；`.mod` / `descriptor.mod` 必须无 BOM。反了就是静默失效。
5. **结论要有出处**。能指到 `documentation/xxx.md:行号` 或原版实例文件的，就指；指不到的，降级并标明。
6. **不要用 `--force` 推`main`**。分支 + PR。

## 错题本格式 · Error Book entry

新建 `references/91_error-book/EB-0NN-<slug>.md`：

```markdown
# EB-0NN：<症状一句话>

## 症状
（界面上/日志里看到什么，原文抄录）

## 错误做法
（常见但错的写法，带代码片段）

## 根因
（引擎为什么这么表现；能指到文档/源码就给行号）

## 标准化方案
（正确写法，可直接抄）

## 验证方式
（怎么确认改对了：命令、预期输出）
```

索引文件 `_index.md` 里加一行；占了 `EB-0NN` 序列要更新编号页。

## 方案库格式 · Solutions entry

`references/92_solutions/SOL-0NN-<slug>.md`，正文含 `status:` 字段（`upstream-only` / `suspect` / `rejected` / `promoted`）。**未验证的思路必须标状态**，验证过就改成 `promoted` 并把结论移进错题本。

## 加一类校验器 · Adding a validator

三步：

1. 在 `mcp-server/validators.py` 写函数，签名 `def check_xxx(root) -> list[dict]`，返回项用 `{"level","file","line","message","hint"}`。
2. 用装饰器注册（`@validator("xxx", category=...)`），自检会自动发现。
3. 在 `examples/broken_mod` 注入一处对应缺陷，并在 `selftest.py` 加断言：它能被抓到，且级别正确。

**必须同时验证假阳性**：拿原版游戏跑 `kiant_hoi4_self_check`，新检查在原版上不应刷出大量 error。刷出来就说明规则太粗。

## 文档与双语 · Docs and bilingual

- 中文是主语言（`README.md`、根文档、`references/`）。
- 英文版与中文版同结构：`README.en.md`。改了中文请顺手同步英文；只改一边也可以，PR 里说明。
- 术语统一：effect / trigger / scope / sprite / localisation 保留英文原词，首次出现给中文解释。

## 提交 · Commit and PR

- 分支名：`feat/xxx`、`fix/xxx`、`docs/xxx`。
- commit message 用中文或英文都行，说清「改了什么、为什么」。
- PR 描述里贴：改了哪些文件、`selftest.py` 结果（贴最后一行通过数）、是否有破坏性变更。
- 涉及新知识域时，说明来源与许可（只能收 MIT/CC 兼容的内容）。

## 行为准则 · Conduct

对人友好，对事实严格。技术分歧拿文件、行号、复现步骤说话，不拿「一般来说」说话。发现别人写错了，直接指出并给改法；被指出时先复核再决定。

## 许可 · License

提交即表示同意以 MIT 许可发布你的贡献（见 [LICENSE](LICENSE)）。上游文档另有出处声明，见 [references/ATTRIBUTION.md](references/ATTRIBUTION.md)。

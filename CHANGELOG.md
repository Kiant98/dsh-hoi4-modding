# 更新日志

## 3.2.1（2026-11-12）

DSH 插件市场（awesome-dsh-plugin）收录适配。只动元数据与文档，未触及脚本。

- **依赖声明**：`package.json` 把宿主提供的 `@deepseek-ai/dsh-mcp-client` 声明为**可选** peer（范围覆盖 0.0.x / 0.1.x / 0.2.x 的预发布分支），符合 DSH 插件生态的依赖约定；宿主未提供时仍按原逻辑回退到 `app.asar` 内置实现，不影响安装。
- **图标**：新增 `assets/`（`icon.svg` 源 + 512 / 180 / 96 PNG 位图），供插件市场卡片与 README 使用；`files` 字段把 `assets/` 打进 npm 包。
- **文档**：README 顶部加图标、版本行与 Release 附件名同步到 3.2.1；`plugin.json` 版本同步。

## 3.2.0（2026-11-09）

DeepSeek Harness 组合包版本。修 3.1.0 在 DSH 插件页报 `{"code":"not-bundle"}` 装不上的问题。

- **组合包声明**：`package.json` 增加 `dsh.bundle.patch`、`type`/`main`/`exports`/`icon`、`engines`（dsh `>=0.2.0 <0.3.0`），新增根 `cordis.patch.yml` 与 `lib/index.js`。npm 包现在可以直接在 DSH 的 设置 → 插件 里安装/更新。
- **技能自动注册**：`lib/index.js` 用 `ctx.skills.registerProvider` 注册 15 个技能（rank 600、按需读 `SKILL.md`，`resourceBase` 指向包内目录），不再需要手动拷贝技能文件。
- **MCP 自动挂载**：插件启动时探测本机 `python`，以 stdio 挂载包内 `mcp-server/server.py`，20 个工具以 `mcp__kiant_hoi4_modkit__kiant_hoi4_*` 出现。可用插件配置 `{"python": "..."}` 指定解释器，`{"mcp": false}` 关闭工具挂载。
- **健壮性**：宿主未提供插件解析时回退到 `app.asar` 内置的 mcp-client；python 探测失败只警告、不阻断技能注册；日志统一 `[dsh-hoi4-modding]` 前缀。
- **图标**：随包分发 `icon.svg`。
- **文档**：README 安装章节改为 DSH 插件页优先，目录树补 `lib/`、`cordis.patch.yml`、`icon.svg`，工具表补齐缺项；`plugin.json` 版本与描述同步。
- 包内自检 330 项仍全绿。

## 3.1.0（2026-11-07）

生态学习五轮之后的版本，重点是把「外部工具怎么做」变成可校验的规则与文档。

- **校验器**：新增 `focus_tree`（国策树语义：前置断链/成环、互斥缺失或自引、同树坐标重叠、`relative_position_id` 断链）与 `loc_commands`（`[Root.GetXxx]` 命令存在性三级分诊：精确命中静默、疑似拼错 warn 给最近建议、未知名 info）两类检查，校验器总数到十二类。
- **参考库**：新增 `93_ecosystem` 8 篇工程解剖（CWTools / GitHub 生态图谱 / 四个 VS Code 插件 / AI agent 工具 / 解析库 / 独立工具 / 大型 mod 官方仓 / hagane-studio），全库参考文档 163 篇。
- **解析器**：`cw.py` 跨游戏写法三修，提升对非 HOI4 Clausewitz 变体的宽容度。
- **自检**：330 项断言全绿；变异测试 17/17。
- **文档**：技能数、工具数、参考库篇数等数字全库统一；补发布流程与平台接入说明。

## 3.0.1（2026-11-07）

- 修复知识库解码链（GBK 文件曾被 `errors="replace"` 变成 U+FFFD 且增量构建永不重试）、中文混排切词、LIKE 转义。
- `remote.py` 的 pull 改为 stage-then-switch（先校验后切换，不再先删旧缓存）。
- `check_defines` 不再误报 Lua 写法。
- 新增 `music` 校验器（`play_song`/电台选曲的 `.asset` 定义与音频文件检查，EB-022）。
- 文档数字与磁盘一致化（错误日志页、错题本、方案库、模块行数）。

## 3.0.0（2026-11-06）

结构性重写：

- 十类可插拔校验器；SQLite + FTS5 知识库（以原版 1.19.4.2 为索引对象）。
- 12 类脚手架、离线 HTML 预览、八阶段规划器、`error.log` 聚类分析。
- 24 条错题本（`EB-`）、10 条方案库（`SOL-`）、6 篇案例区、14 篇开发日志。
- 311 项自检 + 17 项变异测试。
- 153 篇参考库（上游 MIT 文档 + 自撰域文档重组）。

## 2.x / 1.x

早期版本以单一技能 `skills/hoi4-modding` 分发（文档 + Python CLI 脚本），最后一次为 1.4.1。

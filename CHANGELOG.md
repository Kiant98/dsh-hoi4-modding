# 更新日志

## 3.4.0（2026-11-13）

预览层继续往前一步：从「像游戏」变成「按游戏的真实版面排版」，并且补上改盘即刷新。

- **读 `.gui` 几何**：新增 `mcp-server/gui.py`（296 行，纯标准库）。只读解析 `interface/eventwindow.gui`，抽出窗口尺寸与标题、描述、图位、选项按钮的位置/尺寸/字体/底图；解析失败或没有游戏目录时退回内置的原版 1.19 数值，不抛异常。mod 里的同名 `.gui` 优先于原版。
- **事件窗按真实版面渲染**：`preview.py` 不再画自创卡片，改为按几何拼出 581×427 的事件窗——纸纹顶栏、夹纸板、打字机标题、左下图位与 55×30 的三角夹、右列 300×47 的丝带选项按钮。选项文字左对齐，与游戏一致；没有显式选项时写明回退到 `id.a`/`id.b`。窗框按原尺寸内联（新增 `assets.sprite_uri`，不套 128px 上限），九宫格边框不再被压糊。
- **贴图预算调整**：总预算 700 KB → 1.2 MB，另设 900 KB 的界面底图预算；事件图位改为游戏里的 209×176。`examples/sample_mod` 带真机贴图实测 10 张、554 KB、0.39 秒。
- **改盘即刷新**：新增 `tools/kiant-hoi4-watch.py`。起一个只监听 `127.0.0.1` 的小服务并打开浏览器，`/state` 只比对文件签名（快），`/render` 才算真渲染，存盘后 1 秒内自动刷新；`--once` 单次输出到 `<mod>/.modkit/preview.html`，`--game`/`--no-icons`/`--port`/`--interval` 可调。
- **图标解析补前缀**：理念写 `picture = generic_navy_bonus`、决议写 `icon = generic_tank` 时，游戏会自己补 `GFX_idea_` / `GFX_decision_` 前缀；预览之前照着字段原样找，工坊海军 mod 的 280 个理念图标会整片空白。现在候选名先补游戏前缀，同一页 5 张图、0 缺失。
- **自检**：335 → 368 项。新增 `test_gui`（几何解析、大小写不敏感、退回内置值）与 `test_watch`（签名扫描、请求渲染、`--once` 产物）两组，事件窗多 6 条版面断言，另加理念/决议裸名前缀的回归。文档同步到 14 个模块、11417 行。

## 3.3.0（2026-11-13）

预览层重做：从「看结构」变成「看游戏里的样子」。渲染侧全部重写，校验与知识库未动。

- **游戏素材管线**：新增 `mcp-server/assets.py`（612 行，纯标准库）。扫原版与 mod 的 `.gfx` 建 sprite 索引，按 sprite 名取文件，解码 DDS（DXT1/DXT3/DXT5/未压缩 32/24bpp）与 TGA，面积平均缩放后编码成 PNG data URI。本机原版实测 162 个 `.gfx`、22667 个 sprite、建库 0.33 秒、0 失败。
- **预览皮肤**：`preview.py` 换成深色游戏质感（金边标题、渐变节点、点阵底纹），国策节点带真实图标与前置连线，事件改大图卡片（底部渐变遮罩），决议与精神改带图标的卡片网格，取代原来的表格。
- **贴图内联**：生成的 HTML 仍然单文件、无外链，图片以 data URI 直接写进 CSS，同一贴图多次引用只留一条规则。有体积预算（默认 700 KB）与事件大图配额，超了只跳过、不报错；引用不到的 sprite 保持占位，不破坏布局。
- **工具接口**：`kiant_hoi4_preview` 新增 `icons`（默认 true）与 `game_root`（默认自动探测本机安装）两个参数；探测不到游戏目录时静默退回纯结构预览，离线与 CI 不受影响。`examples/sample_mod`：不带图标 13 KB，带图标 98 KB（5 张图，84 KB）。
- **贴图来自本机游戏**：图标与事件图读的是用户自己的安装目录，不随插件分发；页脚会注明来源，生成的文件仍可离线双击打开。
- **自检**：330 → 335 项，新增 5 条贴图断言（data URI 内联、每图一条 CSS 规则、缺失 sprite 占位、同一贴图去重、预算为 0 时不出图）。文档同步到 13 个模块、10775 行。

## 3.2.2（2026-11-12）

文档与呈现升级，代码未改动。

- **首屏截图**：README 顶部加入 `assets/screenshot-focus-tree.png` —— `kiant_hoi4_preview` 对 `examples/sample_mod` 的真实产物（1580×1500），不是示意图。
- **三段真实输出**：新增「能做什么」章节，直接贴 `kiant_hoi4_validate_mod`（`broken_mod` 的 17 项缺陷与 5 条原文报错）、`kiant_hoi4_scaffold`（真实 created 列表）、`kiant_hoi4_preview`（真实 JSON 与截图）的命令与输出。
- **中英双语**：README 顶部加语言切换行，新增 `README.en.md`（全文英译，结构与中文版逐节对应）。
- **贡献指南**：新增 `CONTRIBUTING.md`（中英双语），写明可贡献的 7 类内容、`selftest.py` 330 项门槛、错题本与方案库的提交格式。
- **社区入口**：README 新增「社区与贡献」段（Issues / Discussions / awesome-dsh-plugin 市场条目 / 更新日志 / 上游出处）。
- **数字修正**：后加知识域 38 → 39 篇（34 正文 + 5 索引）；索引源 `refs` 148 → 163 篇。`package.json` / `plugin.json` 版本同步。

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

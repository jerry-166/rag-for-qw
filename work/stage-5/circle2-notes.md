# Stage 5 前端重构 · 圈 2 报告：全局壳 + KB 页按线框 01 重构

> 日期：2026-08-21 | 分支：main | 结论：**达标收敛**

## 1. 改动内容

### 1.1 全局壳（index.html / app.js / main.css）

- **布局**：`.app-layout`（flex + fixed 侧栏）→ `.app-shell`（CSS Grid，232px + 1fr，四周 16px 留边）。折叠用 `:has(.sidebar.collapsed)` 切列宽（232→68px，340ms 过渡），沿用已有折叠态与 localStorage 持久化。
- **侧栏**：浮空玻璃——`position: sticky; top:16px; height: calc(100vh - 32px)`，glass-2（rgba(255,255,255,.075) + blur 22px + saturate 160%）+ 全边框 + 圆角 20px + `inset 0 1px 0` 顶部内高光。
- **topbar**：浮空胶囊——`--glass-topbar-bg`（近实色磨砂）+ blur 32px + `border-radius: 999px` + sticky（top:16px），内含面包屑 / 主题切换 icon-btn / 头像按钮（点击弹用户菜单）。顶栏用户名文本移除（头像弹菜单承载）。
- **统计概览**：5 行列表 → **2×2 数字带**（`.stats-cell`：tabular-nums 大数字 1.15rem/640 + 小标签 .68rem）；admin 追加第 5 格「用户」。旧 stats-toggle 折叠交互删除（线框为常显）。
- **图标**：侧栏 7 项导航 + 主题切换 + 汉堡 + 头像菜单全部换**内联线性 SVG（currentColor）**，替换 emoji（DESIGN §3.1 建议）。主题切换用 `.is-light` 类切月/日图标。
- **用户区**：旧 `.user-info + .btn-logout` → `.user-trigger`（头像+名/角色+chevron 整行可点）→ 弹出**豆包式玻璃菜单**（`.avatar-menu`，fixed + 视口坐标定位 + 边界保护 + Escape/外点关闭，蓝本 = design/page-wireframes/sidebar.js），退出登录移入菜单（含「切换账户」）。
- **断点契约**：≥1024 完整侧栏；768-1023 折叠 68px 图标轨（JS matchMedia 同步 `.collapsed`，不写 localStorage，恢复时回读用户偏好）；<768 侧栏转 fixed overlay 抽屉（transform 滑入 + 遮罩，抽屉态强制完整内容），汉堡按钮显示。旧 `max-width:900px` 页面级媒体查询统一改 1023px。Agent 页高度公式同步新壳（`100vh - 16*2 - 52 - 24`）。
- **KB icon-btn 规范**：新增 `.icon-btn`（32px 命中区，线框规范），`.btn-icon` 同步为透明底 ghost 态。

### 1.2 KB 页（knowledge-bases.js）

- 卡片结构对齐线框：品牌 icon（accent-soft 底 SVG）+ **分享/克隆/编辑/删除四个 icon-btn**（常显，去掉 hover 才显示的旧交互）；KB 名/描述 → **策略徽章行**（`_kbBadges()`：未配策略=「跟随全局」灰 / `auto`→「auto 切割」info；enhancers 双开=「子问题+摘要」accent / 单项 / 空=「纯原文」）→ 更新时间。
- 卡片玻璃化：glass-1 + 浮起 5px + 金色光晕 + **斜向流光扫过**（DESIGN §二 card-hover 配方，亮模式高不透明度白）。
- **分享弹窗**：checkbox → **switch 开关**，语义升级为「允许直接写入（关闭则对方仅能提交 PR，由我审核）」；已分享列表改徽章（可写入=绿 / 仅 PR=灰）+「取消分享」ghost 按钮。
- KB 名/描述经 `_esc` 转义（顺带 XSS 加固）。

### 1.3 顺带清理

- **圈 1 桥接自引用问题**：删除 main.css 头部旧 `:root`/`body.light-mode` 覆盖块（靛紫硬编码），桥接层 `--accent` 改回 `var(--accent)` 引用（此前因旧块覆盖被迫写死字面值）；补齐 `--radius*/--shadow*/--sidebar*/--transition` 兼容别名。
- **pipeline.js 统计加载 NPE**（旅程 console error #2 根因）：壳改为 navigate 整体重渲染后 `global-*` 元素可能已随 DOM 切换消失，逐项判空（`setStat`）。旅程 console error 由 2 → 1（仅剩基线固有的 PDF.js 对 .md 报 InvalidPDF）。
- **后端**：`GET /api/knowledge-bases` 响应补 `chunk_strategy`/`enhancers` 字段（DB 行本就有 `kb.*`，只是响应漏带）——策略徽章数据源。
- `.btn-primary:hover` 硬编码靛紫 `#5254c8` → `var(--accent2)`。

## 2. 验证数据（客观命令结果）

- `node --check`：app.js / knowledge-bases.js / pipeline.js 全 OK；后端 `ast.parse` OK。
- **冒烟**（work/stage-5/circle2/smoke.js，Playwright）：
  - 壳计算样式：sidebar `position:sticky; top:16px; bg rgba(255,255,255,.075); blur(22px) saturate(1.6); radius 20px`；topbar `sticky; radius 999px; bg rgba(11,13,19,.78); blur(32px)`；统计数字 `font-variant-numeric: tabular-nums`。
  - 建 KB（auto + 双增强器）→ 徽章 = `auto 切割 / 子问题+摘要`；编辑改名成功（EDIT-OK: true）。
  - 折叠：宽 68px、grid `68px 1324px`；头像弹菜单出现（AVATAR-MENU: 1）→ 退出登录回到登录页（LOGOUT-OK: true）→ 重新登录。
  - 亮色切换 LIGHT: true；中屏 900px → 68px 图标轨（MID-RANGE）；480px → 抽屉滑出（DRAWER: open, leftVisible, 280px）。
  - **console error 0**。
- **journey.spec.js 全旅程：15/15 PASS，console errors/warnings 1（仅基线固有的 PDF.js InvalidPDF，较圈 1 的 2 个再减 1），bad requests 0**。
- 截图：`work/stage-5/circle2/shots/`（01-shell-kb / 02-kb-created / 03-kb-edited / 04-sidebar-collapsed / 05-avatar-menu / 06-light-mode / 07-midrange-rail / 08-mobile-drawer + 旅程全量 01-10）。
- 测试残留清理：9 个 `stage5-circle2-*` KB 已全部 DELETE 200，复核 remaining=0（旅程 KB `stage5-baseline-2026-08-21T15-10-39`、file_id=152 保留，与圈 1 惯例一致）。
- 结束后 8000/8003 服务已杀净（见提交前 netstat 复核）。

## 3. 行为红线核验

登录/登出（头像菜单路径）✓、导航高亮 ✓、主题切换 ✓、KB CRUD（建/改含策略字段/删）✓ —— 均由冒烟+旅程实测覆盖。

## 4. 提交清单

- `frontend/index.html`（壳模板重构 + SVG 图标 + 缓存版本参数）
- `frontend/js/app.js`（avatar 菜单/logout、统计 2×2、中屏折叠同步、主题图标）
- `frontend/js/pages/knowledge-bases.js`（卡片重构、策略徽章、分享开关语义、_esc）
- `frontend/js/pages/pipeline.js`（统计加载判空）
- `frontend/css/main.css`（壳/KB 卡/响应式/桥接层清理/icon-btn/badge 变体）
- `backend/api/knowledge_bases.py`（列表响应补策略字段）
- `work/stage-5/circle2-notes.md` + `work/stage-5/circle2/`（smoke.js、journey、shots、raw-results）

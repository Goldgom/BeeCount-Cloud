# BeeCount Cloud 前端重构交付

日期：2026-10-25（用户时间 GMT+8）
范围：仅 `frontend/`。未修改服务端、未部署、未提交 git。初始 `git status --short` 为空；后续可见服务端文件变更来自其他协作会话，未触碰。

## 视觉系统

- 重建深浅色语义令牌、系统字体、低对比边框、分组卡片、留白、层级和低幅动效。
- 桌面新增固定侧栏；中屏保留顶部导航；小屏保留带安全区的底部导航。原路由/API保持兼容。
- 共享 Card/Button/Input/Tabs/ListTableShell 真正重构，不是末尾堆叠覆盖 CSS。
- 默认蓝色主题，保留用户本地及服务端主题偏好；自动计算按钮前景黑白对比；暗色 accent 不再使用亮色底。
- HomeHero、HomeHabitStats、OverviewSection、账户卡和交易工具栏重排，去除大面积彩色渐变、光斑、激光纹理及“扩展分析”标语。
- 登录页收敛为单一品牌和登录表单；保留 2FA、错误、安全提示与语言/主题切换。
- skip link、focus-visible、aria-current/aria-pressed、键盘账户卡、滚动表格区域、reduced motion。

## 资产准确性

- API 类型对接 P0 的 nullable 原币估值/收益、基准币字段、快照模式、FX 路径、coverage/completeness/as_of。
- 全资产优先使用 `all_assets_summary`（现金 + 持仓 + 剩余应收），不叠加投资账户总资产，不重复现金。
- 带符号净值；正负组件拆资产和负债。缺估值用 `known_total_assets`，明确“部分净资产（已知小计）”。
- 覆盖数、基准币、生成时点独立展示；详情逐项展示原币、基准币金额、汇率路径/来源/日期和观察时点。
- 投资表统一用于首页、资产页、账户详情，声明 investment-only 范围。未知金额/收益为 —，不强制零，不调用 null.toFixed。
- 快照模式隐藏份额/单位成本/市场报价，显示金额快照来源及日期；混合观察时点不宣称实时；过期 FX 提示。
- 单一外币及仅投资产品涉及外币也加载主币种汇率；缺汇率提示不再依赖 rate_date；拒绝旧缓存中基准币不匹配的自动汇率。
- 历史走势保留原功能，但明确“仅账户余额，不含持仓和应收”，不能与当前全资产净值直接比较。
- 账户投资卡未知持仓不回退零；首页 analytics 未返回时主要金额不展示虚假零结余。

## 账务入口（主会话追加授权）

新增 `/app/finance`，桌面侧栏及资产页可进入，移动端通过资产页进入。

- 余额核对：观察余额/币种、目标余额、来源、原因；传 expected_balance 做并发冲突检查，不修改期初，不伪装收入支出；成功显示 before/after/difference 与事件 ID。
- 双边转账：独立转出和到账金额、账户币种、唯一外部编号、可选转出账户手续费。
- 应收登记、分期到期安排、部分回款（可选绑定分期、只列同币种回款账户）。
- 应收余额、分期剩余及事件 effects 日志可见。
- 所有写入使用后端 authedPost + Idempotency-Key；相同请求不确定失败后保留 key。核对有效时点冻结后重试，不每次生成新时点。
- loading / error / retry / success / empty 状态；写入成功后刷新读数据，WS 同步亦刷新。

## 验证

使用锁文件安装：`cd frontend && corepack pnpm install --frozen-lockfile` 成功；未改依赖/锁文件。

最终执行：

1. `cd frontend && corepack pnpm -C apps/web build` — **exit 0**，含 `tsc -b` 与 Vite production build，最新产物 `frontend/apps/web/dist/`。
2. `cd frontend && corepack pnpm -C apps/web test` — **exit 0**，**12 文件 / 77 测试全部通过**。
3. `git diff --check -- frontend` — **exit 0**（仅 LF/CRLF 提示，无 whitespace error）。

新增/加强：
- unknown/null/NaN/Infinity 收益不当零；真实零保持中性。
- 观察时点不替代为响应时间。
- 服务端静态渲染持仓组件：空估值不崩溃、原币、coverage、非全资产语义、快照展示。
- 汇率缓存基准不匹配拒绝。
- finance 路由 roundtrip。
- finance 客户端认证、Idempotency-Key、decimal string 原样传输、读接口路径。
- 补齐原有繁中缺失文案，i18n parity 全绿。

构建非阻断警告：浏览器兼容性数据库较旧；依赖包 use-client 指令被 bundler 忽略；主入口 gzip 约243KB/minified约846KB触发现有800KB提示。未以修改阈值隐藏警告。

## 运行时验证边界

本会话完成类型、生产构建、单元/组件 SSR 和请求契约验证；未操作真实用户资产。
主会话已启动 `18765` 本地独立空库进行浏览器验收，已通知其刷新最新 dist。浏览器截图及真实空库 POST 核对/转账/分期回款由主会话记录；本文不把静态验证冒充这些运行结果。

## 保留边界

本轮新增金融 UI 覆盖明确要求的核对/双边转账/应收分笔回款；未增加冲正、快照/期间归因报表操作界面（后端能力不等于 UI 已交付），未配置定时后台任务。

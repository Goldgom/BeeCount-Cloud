# 投资/全部资产核算契约

REST `GET /api/v1/read/investment-assets` 与注册 MCP `get_investment_assets` 调用同一 `services.investment_valuation.investment_assets`。查询仅消费 projection 与云投资/finance event 表，不改写历史账本或 ledger_snapshot。

## 范围与金额

- 顶层 `scope=investment_only`，`total_market_value` 仅持仓，`total_cash_balance` 仅投资账户现金，`total_assets`/`net_equity` 为两者有符号净合计。不是全部资产，也不是可用余额。
- `all_assets_summary.scope=all_assets`：全部账户现金 + 独立持仓 + P1 未偿应收；不得再次加账户的含持仓 `total_assets`，否则双算。`all_assets_total` 是此汇总的兼容快捷值。
- `total_assets` 历史名称表示有符号净合计，与 `net_equity` 相同，不是正资产毛额。可按 components 正负分别展示资产/负债。
- `available_balance=null` 表示未报告；不把现金或净权益冒充券商可用余额。
- 持仓 `market_value/daily_pnl/holding_pnl/cost_basis_total` 是 `currency` 原币；对应 `*_base` 是用户基准币。账户的 `holdings_market_value/daily_pnl/total_assets` 已换成账户自身 `currency`，`*_base` 是用户基准币。
- 折算逐项保留小数，汇总最终舍入至两位。展示逐项可自行格式化，不能反向用展示数计算精确总额。

## 汇率

`fx={status: identity|converted|missing_rate,rate:string|null,path:[{from_currency,to_currency,rate,source,rate_date,fetched_at,stale}],stale}`。

优先用户手动汇率 projection（方向 `1 quote = rate base`），其次可溯源 provider 缓存（方向 `1 base = rate quote`）；支持倒数与多跳。手动重复币对按 source_change_id/updated_at/sync_id 决胜。用户隔离，非正数/非有限汇率不使用。按服务配置允许 provider 时才惰性获取新汇率。USDT 不隐含等于 USD；缺汇率永不退回 1:1。

## 估值模式/CRUD

- `shares_nav`：quantity × current_price。未报价即未知，不以成本冒充当前市值。总成本 quantity × 单位 cost_basis；清仓总成本 0。缺成本或收益资料为 null，不补零。
- `money_fund`：NAV=1；累计成本来自 net_subscription_principal，日收益来自 daily_income 或有来源的万份收益。未提供本金或日收益则未知，不假设 quantity 就是本金。
- `amount_snapshot`：snapshot_amount 是整笔金额，不乘 quantity，不推断成本/收益。必须提供 snapshot_amount、snapshot_at、valuation_source。
- REST create/patch 与 MCP create/update 复用 Pydantic 校验和同一持久化实现。`clear_cost_basis=true` 是两端共同的清空成本命令；REST 另可显式 cost_basis=null。MCP `use_auto_price=true` 清除手动价，恢复自动报价。
- MCP get/list 输出 valuation_mode/snapshot_amount/snapshot_at/valuation_source。真实工具注册 schema 同步包含以上输入。

## 完整性与时点

任何必要项未知，则完整合计为 null；`known_market_value/known_cash_balance/known_total_assets` 是可明确展示的已知小计。顶层 coverage 指明持仓/现金项数量、缺失持仓和未绑定持仓。全部资产 coverage 指明组件数量和缺失组件 ID。

`completeness=complete|partial` 只描述金额覆盖，不宣称所有估值同一时点。`as_of` 是服务生成响应时点；`as_of_status=mixed_observation_times`。每项有 as_of，报价有 price_updated_at，快照有 snapshot_at，现金有 cash_as_of；`valuation_times_complete/cash_times_complete` 单独声明时点覆盖，`fx_stale` 声明陈旧汇率。

## 迁移

`0025_investment_valuation` 依赖 `0024_finance_events`。仅投资表 cost_basis 变为 nullable，并新增 valuation_mode/snapshot_amount/snapshot_at/valuation_source。不猜测既存零成本是否未知、不修改历史账本。降级遇到未知成本会拒绝，而非把 null 擅自改零。

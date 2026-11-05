# Vegas Sandbox — BTC EMA Audit

独立实验仓库，只用于研究与验证。不会连接或修改 V12、V4 的运行配置。

## 本次实验
- 标的：Bitget USDT 永续 BTCUSDT
- 评估窗口：运行时向前 184 天
- 预热数据：评估窗口之前最多 365 天（交易所可提供多少就使用多少）
- K线：1H、4H；仅保留已收盘K线
- 对比：V12 旧版 EWM 初始化、V12 PR #8 的 SMA 初始化、V4 的 SMA 初始化
- 额外检查：只用评估窗口数据初始化时，EMA 对历史起点的敏感度

## 运行
首次加入工作流的 push 会触发一次运行；以后也可在 Actions 手动运行。
工作流不设 schedule，不发送 Bark，不部署，不访问 V12/V4 写接口。
报告与原始K线 CSV 作为 Actions artifact 保存。

## 重要限制
V4 的 EMA 参考公式来自 assets/js/indicators/ema-v4.js：
首 N 根 close 的算术平均作为初值，之后按 alpha=2/(N+1) 递推。
V12 旧公式来自 V12 signal_rules.py 的 pandas ewm(span, adjust=False, min_periods=span)。
本实验验证计算公式和 Bitget K线输入上的数值差异，不把 EMA 数值对齐误称为交易所图表端直接读数比对。

## Isolation
This repository has no scheduled workflow, no Bark token, and no deployment target.

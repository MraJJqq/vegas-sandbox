# Vegas Bottom Signal · Sandbox

独立静态底部信号展示测试页。仅修改本分支，不接触 V9 页面，也不改动 A 股扫描器。

## 展示规则

- 固定屏幕底部，水平居中。
- 静态显示，不滚动、不循环、不复制信号内容。
- 多个品种按 Bark 扫描输出顺序排列，使用 `▰` 分隔。
- 不显示方向，不分类，显示品种时去掉 `USDT`。
- 成功扫描但信号为空时显示 `𝐍𝐨 𝐒𝐢𝐠𝐧𝐚𝐥`。
- 数据缺失、过期、格式错误或网络失败时显示“等待信号数据”。

## 沙盒预览

部署完成后：

- 演示布局（模拟品种，明确标注 DEMO）：站点地址追加 `?demo=1`。
- 实时 Bark 数据：直接打开站点根地址。Bark JSON 尚未发布时会显示“等待信号数据”。

真实 feed：

`https://raw.githubusercontent.com/MraJJqq/Vegasbark/main/public/signals.json`

## Bark feed contract

```json
{
  "schema_version": 1,
  "source": "Vegasbark",
  "generated_at": "2026-11-23T08:00:00+08:00",
  "symbols": ["BTC", "ETH"]
}
```

网页每 60 秒刷新一次；feed 最长有效期 7 小时。后台标签页暂停刷新，回到前台立即刷新。

## Tests

`node --test tests/test_signal_feed.mjs tests/test_static_preview.mjs`

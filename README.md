# Vegas Signal Sandbox

独立的底部信号展示沙盒，不修改 V9 或 Vegasbark 的扫描逻辑。

## 展示规则
- 固定在屏幕右下角，适配桌面、平板和手机全屏尺寸。
- 信号按 Bark feed 的顺序逐条排列；数量较多时自适应多列。
- 不使用横向滚动，不设置滚动列表；全部信号同时可见。
- 新数据以轻量渐入动画更新。
- 每 15 秒读取一次 Bark 的公开 feed；保留 Bark 输出的原始品种顺序。
- feed 尚未首次发布时显示等待状态，不伪装成“无信号”。

## 数据源
`https://raw.githubusercontent.com/MraJJqq/Vegasbark/main/public/signals.json`

Feed contract: `schema_version=1`, `source="Vegasbark"`, `generated_at`, `symbols[]`.

## Deploy
GitHub Actions publishes this repository root to GitHub Pages after each push to `main`.

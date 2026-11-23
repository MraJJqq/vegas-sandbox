# Bottom Signal Ticker (Sandbox)

独立底部信号模块。此目录不改动 A 股扫描器，也不接触 V9 页面。

## Bark feed contract

网页只读取 Bark 发布的只读 JSON，不读取手机通知，也不自行计算信号。

预期地址：

`https://raw.githubusercontent.com/MraJJqq/Vegasbark/main/public/signals.json`

协议：

```json
{
  "schema_version": 1,
  "source": "Vegasbark",
  "generated_at": "2026-11-23T08:00:00+08:00",
  "symbols": ["BTC", "ETH"]
}
```

`symbols` 必须保持 Bark 扫描器输出顺序；可以为空数组。空数组仅表示一次成功完成的扫描确实没有信号。缺文件、过期、格式错误或网络失败均显示“等待信号数据”，绝不伪装成 No Signal。

**接入状态：接口消费者与协议已实现；Bark 端尚未发布该 JSON 文件，因此真实数据链路尚未打通。** 完成 Bark 发布端后，再把 feed URL 配入 V9。

## Mount

在宿主页面引入 CSS，并从模块中调用：

```js
import { mountBottomSignalTicker } from "./bottom-signal/bottom-signal.mjs";

const ticker = mountBottomSignalTicker({
  root: document.querySelector("#bottom-signal"),
  feedUrl: "https://raw.githubusercontent.com/MraJJqq/Vegasbark/main/public/signals.json"
});
```

销毁时调用 `ticker.destroy()`。模块每 60 秒拉取一次；信号有效期设为 7 小时以覆盖 Bark 每日扫描间隔；后台暂停；恢复前台后立即刷新。信号顺序与 Bark 一致，显示时去掉 USDT，不显示方向，不做分类。

## Tests

`node --test tests/test_signal_feed.mjs`

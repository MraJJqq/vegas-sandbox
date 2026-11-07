# Binance USD-M market-data module

This branch contains an independent public market-data client for Binance USDⓈ-M
perpetual futures. It is isolated from V5/V12 and does not change the existing
Bitget or A-share pipelines.

## Connection model

- REST endpoint: https://fapi.binance.com
- Live WebSocket: wss://fstream.binance.com/ws
- Public market data requires no API key.
- Native intervals include 4h, 8h, 12h and 1d.
- klines_range() paginates historical candles without resampling.
- EMA spans 12, 144, 169, 576 and 676 use an SMA seed followed by standard EMA.
- HTTP 451 is surfaced as a regional access restriction; no bypass is attempted.

## Run locally

    python -m pip install -r requirements.txt
    python scripts/binance_um_data.py --history-bars 800

The generated report.md and binance-connectivity.json record symbol availability,
candle counts, latest candles, EMA readiness, REST status and WebSocket handshake.

The default verification set is XAUUSDT, BTCUSDT, CLUSDT and SNDKUSDT.
A missing symbol is reported as unavailable rather than substituted.
BTCUSDT is the baseline connectivity instrument.

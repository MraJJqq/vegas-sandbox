#!/usr/bin/env python3
"""Compare the exact 27 Media instruments against live Binance USD-M and Gate USDT futures contract lists."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

BINANCE = "https://fapi.binance.com/fapi/v1/exchangeInfo"
GATE = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
# Canonical 27-symbol universe read from Media/modules/shared/universe-v4.js.
# The logo slug is the exact filename stem under Media/Logos.
INSTRUMENTS = [
 ("apple","AAPL","AAPLUSDT","AAPL_USDT"),
 ("amd","AMD","AMDUSDT","AMD_USDT"),
 ("amazon","AMZN","AMZNUSDT","AMZN_USDT"),
 ("arm","ARM","ARMUSDT","ARM_USDT"),
 ("asml","ASML","ASMLUSDT","ASML_USDT"),
 ("broadcom","AVGO","AVGOUSDT","AVGO_USDT"),
 ("cerence","CBRS","CBRSUSDT","CBRS_USDT"),
 ("corning","GLW","GLWUSDT","GLW_USDT"),
 ("google","GOOGL","GOOGLUSDT","GOOGL_USDT"),
 ("intel","INTC","INTCUSDT","INTC_USDT"),
 ("marvell","MRVL","MRVLUSDT","MRVL_USDT"),
 ("meta","META","METAUSDT","META_USDT"),
 ("micron","MU","MUUSDT","MU_USDT"),
 ("microsoft","MSFT","MSFTUSDT","MSFT_USDT"),
 ("nvidia","NVDA","NVDAUSDT","NVDA_USDT"),
 ("oracle","ORCL","ORCLUSDT","ORCL_USDT"),
 ("qualcomm","QCOM","QCOMUSDT","QCOM_USDT"),
 ("robinhood","HOOD","HOODUSDT","HOOD_USDT"),
 ("sandisk","SNDK","SNDKUSDT","SNDK_USDT"),
 ("sk-hynix","SKHYNIX","SKHYUSDT","SKHY_USDT"),
 ("spacex","SPCX","SPCXUSDT","SPCX_USDT"),
 ("tesla","TSLA","TSLAUSDT","TSLA_USDT"),
 ("tsmc","TSM","TSMUSDT","TSM_USDT"),
 ("bitcoin","BTC","BTCUSDT","BTC_USDT"),
 ("crude-oil","CL","CLUSDT","CL_USDT"),
 ("gold","XAU","XAUUSDT","XAU_USDT"),
 ("hyperliquid","HYPE","HYPEUSDT","HYPE_USDT"),
]

def get_json(url):
    r = requests.get(url, timeout=20, headers={"Accept":"application/json","User-Agent":"vegas-sandbox-universe-audit/1.0"})
    r.raise_for_status()
    return r.json()

def main():
    report = {
      "generated_at_utc": datetime.now(timezone.utc).isoformat(),
      "universe_source": "MraJJqq/Media/modules/shared/universe-v4.js + Media/Logos/",
      "count": len(INSTRUMENTS),
      "binance": {"endpoint": BINANCE, "status":"pending"},
      "gate": {"endpoint": GATE, "status":"pending"},
      "rows": []
    }
    binance_set = set()
    gate_set = set()
    try:
        info = get_json(BINANCE)
        binance_set = {x.get("symbol") for x in info.get("symbols", []) if x.get("contractType") == "PERPETUAL" and x.get("quoteAsset") == "USDT"}
        report["binance"].update(status="ok", perpetual_usdt_count=len(binance_set))
    except Exception as e:
        report["binance"].update(status="failed", error=str(e)[:600])
    try:
        contracts = get_json(GATE)
        gate_set = {x.get("name") for x in contracts if x.get("in_delisting") is not True}
        report["gate"].update(status="ok", usdt_contract_count=len(gate_set))
    except Exception as e:
        report["gate"].update(status="failed", error=str(e)[:600])
    for slug, canonical, bitget, gate_expected in INSTRUMENTS:
        b_symbol = canonical + "USDT"
        g_symbol = gate_expected
        b_checked = report["binance"]["status"] == "ok"
        g_checked = report["gate"]["status"] == "ok"
        report["rows"].append({
          "media_logo": slug,
          "canonical_symbol": canonical,
          "bitget_reference": bitget,
          "binance_expected": b_symbol,
          "binance_actual": b_symbol if b_checked and b_symbol in binance_set else None,
          "binance_match": (b_symbol in binance_set) if b_checked else None,
          "gate_expected": g_symbol,
          "gate_actual": g_symbol if g_checked and g_symbol in gate_set else None,
          "gate_match": (g_symbol in gate_set) if g_checked else None,
        })
    report["comparison_summary"] = {
      "binance_matches": sum(r["binance_match"] is True for r in report["rows"]),
      "binance_not_found": sum(r["binance_match"] is False for r in report["rows"]),
      "binance_unverified": sum(r["binance_match"] is None for r in report["rows"]),
      "gate_matches": sum(r["gate_match"] is True for r in report["rows"]),
      "gate_not_found": sum(r["gate_match"] is False for r in report["rows"]),
      "gate_unverified": sum(r["gate_match"] is None for r in report["rows"]),
    }
    out=Path("results/gate-27-universe-audit")
    out.mkdir(parents=True,exist_ok=True)
    (out/"comparison.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=[
      "# Media 27 instruments — Binance vs Gate contract-name audit","",
      f"- Time (UTC): {report['generated_at_utc']}",
      f"- Media universe count: {len(INSTRUMENTS)}",
      f"- Binance contract list: **{report['binance']['status']}**",
      f"- Gate contract list: **{report['gate']['status']}**","",
      "| Media logo | Canonical code | Bitget reference | Binance exact name | Binance | Gate exact name | Gate |",
      "|---|---|---|---|---|---|---|"
    ]
    for r in report["rows"]:
        b = "匹配" if r["binance_match"] is True else ("未找到" if r["binance_match"] is False else "未核实")
        g = "匹配" if r["gate_match"] is True else ("未找到" if r["gate_match"] is False else "未核实")
        lines.append(f"| {r['media_logo']} | {r['canonical_symbol']} | {r['bitget_reference']} | {r['binance_actual'] or '—'} | {b} | {r['gate_actual'] or '—'} | {g} |")
    s=report["comparison_summary"]
    lines += ["","## Summary",
      f"- Binance: {s['binance_matches']} matched; {s['binance_not_found']} not found; {s['binance_unverified']} unverified.",
      f"- Gate: {s['gate_matches']} matched; {s['gate_not_found']} not found; {s['gate_unverified']} unverified.",
      "",
      "Note: “not found” means absent from the live USDT perpetual contract list returned by the official endpoint; it is not a claim that the underlying asset does not exist on the exchange.",
      "This job only compares contract names. It does not request candlesticks or subscribe to market streams."]
    if report["binance"].get("error"): lines += ["", "Binance error: "+report["binance"]["error"]]
    if report["gate"].get("error"): lines += ["", "Gate error: "+report["gate"]["error"]]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))
    # Keep the audit successful even if an exchange blocks access; report distinguishes unverified.
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only 27-instrument Gate USDT perpetual REST + native 4H/8H WebSocket audit."""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path
import requests
import websocket

REST = "https://api.gateio.ws/api/v4"
WS = "wss://fx-ws.gateio.ws/v4/ws/usdt"
INSTRUMENTS = [
 ("apple","AAPL","AAPL_USDT"),("amd","AMD","AMD_USDT"),
 ("amazon","AMZN","AMZN_USDT"),("arm","ARM","ARM_USDT"),
 ("asml","ASML","ASML_USDT"),("broadcom","AVGO","AVGO_USDT"),
 ("cerence","CBRS","CBRS_USDT"),("corning","GLW","GLW_USDT"),
 ("google","GOOGL","GOOGL_USDT"),("intel","INTC","INTC_USDT"),
 ("marvell","MRVL","MRVL_USDT"),("meta","META","META_USDT"),
 ("micron","MU","MU_USDT"),("microsoft","MSFT","MSFT_USDT"),
 ("nvidia","NVDA","NVDA_USDT"),("oracle","ORCL","ORCL_USDT"),
 ("qualcomm","QCOM","QCOM_USDT"),("robinhood","HOOD","HOOD_USDT"),
 ("sandisk","SNDK","SNDK_USDT"),("sk-hynix","SKHYNIX","SKHY_USDT"),
 ("spacex","SPCX","SPCX_USDT"),("tesla","TSLA","TSLA_USDT"),
 ("tsmc","TSM","TSM_USDT"),("bitcoin","BTC","BTC_USDT"),
 ("crude-oil","CL","CL_USDT"),("gold","XAU","XAU_USDT"),
 ("hyperliquid","HYPE","HYPE_USDT")
]
INTERVALS=("4h","8h")

def get_json(url, params=None):
    r=requests.get(url,params=params,timeout=20,headers={"Accept":"application/json","User-Agent":"vegas-sandbox-gate-27-probe/1.0"})
    r.raise_for_status()
    return r.json()

def rest_test():
    result={}
    contracts=get_json(f"{REST}/futures/usdt/contracts")
    live={x.get("name"):x for x in contracts}
    for slug,code,name in INSTRUMENTS:
        row={"media_logo":slug,"canonical_symbol":code,"contract":name,
             "listed":name in live,"timeframes":{}}
        if name in live:
            row["contract_status"]=live[name].get("status")
            for interval in INTERVALS:
                try:
                    data=get_json(f"{REST}/futures/usdt/candlesticks",
                                  {"contract":name,"interval":interval,"limit":3})
                    valid=isinstance(data,list) and len(data)>0 and all(
                        all(k in candle for k in ("t","o","h","l","c")) for candle in data)
                    row["timeframes"][interval]={
                        "status":"ok" if valid else "invalid_or_empty",
                        "bars":len(data) if isinstance(data,list) else 0,
                        "latest":data[-1] if valid else None,
                    }
                except Exception as e:
                    row["timeframes"][interval]={"status":"failed","error":str(e)[:400]}
        else:
            row["timeframes"]={i:{"status":"not_tested_contract_missing"} for i in INTERVALS}
        result[name]=row
    return result

def websocket_test():
    result={"url":WS,"status":"failed","subscribed":[],"live_updates":{},
            "errors":[],"wait_seconds":60}
    ws=None
    try:
        ws=websocket.create_connection(WS,timeout=12,enable_multithread=True)
        ws.settimeout(2)
        expected={(name,interval) for _,_,name in INSTRUMENTS for interval in INTERVALS}
        request_map={}
        for request_id,(name,interval) in enumerate(sorted(expected), start=1):
            request_map[request_id]=(name,interval)
            ws.send(json.dumps({"time":int(time.time()),"id":request_id,
                                "channel":"futures.candlesticks","event":"subscribe",
                                "payload":[interval,name]}))
        ack=set()
        deadline=time.time()+60
        while time.time()<deadline and (len(ack)<len(expected) or len({k.split(":",1)[0] for k in result["live_updates"]})<len(INSTRUMENTS)):
            try:
                raw=ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw: continue
            try: msg=json.loads(raw)
            except Exception: continue
            if msg.get("channel")!="futures.candlesticks": continue
            if msg.get("event")=="subscribe":
                request_id=msg.get("id")
                key=request_map.get(request_id)
                if key in expected and msg.get("error") is None:
                    ack.add(key)
                elif msg.get("error") is not None:
                    result["errors"].append({"subscription":key,"error":msg.get("error"),"result":msg.get("result")})
            elif msg.get("event")=="update":
                items=msg.get("result")
                if isinstance(items,dict):
                    items=[items]
                if isinstance(items,list):
                    for item in items:
                        if not isinstance(item,dict): continue
                        stream=item.get("n","")
                        if "_" not in stream: continue
                        interval,name=stream.split("_",1)
                        key=(name,interval)
                        if key in expected and all(k in item for k in ("t","o","h","l","c")):
                            result["live_updates"][f"{name}:{interval}"]=item
        result["acknowledged"]=[f"{name}:{interval}" for name,interval in sorted(ack)]
        active_instruments={k.split(":",1)[0] for k in result["live_updates"]}
        result["status"]="all_27_instruments_live" if len(active_instruments)==len(INSTRUMENTS) else ("partial_live_updates" if active_instruments else "no_live_updates")
        result["acknowledged_count"]=len(ack)
        result["expected_subscriptions"]=len(expected)
        result["live_update_count"]=len(result["live_updates"])
        result["live_instrument_count"]=len(active_instruments)
        result["live_instruments"]=sorted(active_instruments)
    except Exception as e:
        result["error"]=str(e)[:600]
    finally:
        if ws:
            try: ws.close()
            except Exception: pass
    return result

def main():
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "market":"Gate.io USDT perpetual futures",
            "source_universe":"MraJJqq/Media/modules/shared/universe-v4.js + Media/Logos/",
            "instrument_count":len(INSTRUMENTS),"intervals":list(INTERVALS),
            "rest":{},"websocket":{}}
    try: report["rest"]=rest_test()
    except Exception as e: report["rest_error"]=str(e)[:600]
    report["websocket"]=websocket_test()
    rest_rows=list(report["rest"].values())
    report["summary"]={
      "contracts_found":sum(x.get("listed") is True for x in rest_rows),
      "contracts_missing":sum(x.get("listed") is False for x in rest_rows),
      "rest_4h_success":sum(x.get("timeframes",{}).get("4h",{}).get("status")=="ok" for x in rest_rows),
      "rest_8h_success":sum(x.get("timeframes",{}).get("8h",{}).get("status")=="ok" for x in rest_rows),
      "ws_live_instruments":report["websocket"].get("live_instrument_count",0),
      "ws_expected_instruments":len(INSTRUMENTS),
      "ws_acknowledged_streams":report["websocket"].get("acknowledged_count",0),
      "ws_expected_streams":len(INSTRUMENTS)*len(INTERVALS)
    }
    report["overall_status"]="complete" if (
      report["summary"]["contracts_found"]==27 and
      report["summary"]["rest_4h_success"]==27 and
      report["summary"]["rest_8h_success"]==27 and
      report["summary"]["ws_live_instruments"]==27 and
      report["summary"]["ws_acknowledged_streams"]==54
    ) else "partial"
    out=Path("results/gate-27-market-data");out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Gate 27-instrument native market-data test","",
      f"- Time UTC: {report['generated_at_utc']}",
      f"- Overall: **{report['overall_status']}**",
      f"- Contracts found: {report['summary']['contracts_found']}/27",
      f"- Native 4H REST: {report['summary']['rest_4h_success']}/27",
      f"- Native 8H REST: {report['summary']['rest_8h_success']}/27",
      f"- WebSocket live instruments: {report['summary']['ws_live_instruments']}/27",
      f"- WebSocket acknowledged interval streams: {report['summary']['ws_acknowledged_streams']}/54","",
      "| Media logo | Code | Gate contract | Listed | 4H REST | 8H REST | 4H WS | 8H WS |",
      "|---|---|---|---|---|---|---|---|"]
    live=report["websocket"].get("live_updates",{})
    for slug,code,name in INSTRUMENTS:
        x=report["rest"].get(name,{})
        tf=x.get("timeframes",{})
        lines.append(f"| {slug} | {code} | {name} | {'是' if x.get('listed') else '否'} | {tf.get('4h',{}).get('status','—')} | {tf.get('8h',{}).get('status','—')} | {'收到' if f'{name}:4h' in live else '未收到'} | {'收到' if f'{name}:8h' in live else '未收到'} |")
    if report.get("rest_error"): lines += ["","REST error: "+report["rest_error"]]
    if report["websocket"].get("error"): lines += ["","WebSocket error: "+report["websocket"]["error"]]
    if report["websocket"].get("errors"): lines += ["","## Subscription errors"]+[f"- {x}" for x in report["websocket"]["errors"]]
    lines += ["","All data requests are public/read-only. No orders or account authentication are used.",
              "REST candles request native 4h and 8h intervals; no timeframe resampling."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations
import csv, json, math, statistics, time, io, zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests

BG = "https://api.bitget.com"
BN_ARCHIVE = "https://data.binance.vision"
ASSETS = {"XAUUSDT":"Gold", "BTCUSDT":"Bitcoin", "CLUSDT":"WTI crude oil", "SNDKUSDT":"SanDisk"}
TF = {
    "4H": (4*3600000, "4H", "4h"),
    "8H": (8*3600000, "1H_AGGREGATED", "8h"),
    "12H": (12*3600000, "12Hutc", "12h"),
    "1D": (24*3600000, "1Dutc", "1d"),
}
SPANS = (12, 144, 169, 576, 676)
S = requests.Session()
S.headers.update({"User-Agent":"vegas-sandbox-exchange-audit/1.0"})

def get(url, params=None):
    err = None
    for i in range(5):
        try:
            r = S.get(url, params=params, timeout=35)
            if r.status_code in (418,429,500,502,503,504):
                raise RuntimeError("HTTP %s %s" % (r.status_code, r.text[:180]))
            r.raise_for_status()
            obj = r.json()
            if isinstance(obj,dict) and obj.get("code") not in (None,"00000",0,"0"):
                raise RuntimeError("API %s: %s" % (obj.get("code"),obj.get("msg")))
            return obj
        except Exception as e:
            err=e
            if i < 4: time.sleep(min(2**i,12))
    raise RuntimeError(str(err))

def msval(v):
    try:
        x=int(v)
        return x if x>0 else None
    except Exception:
        return None

def candle(x):
    try:
        return {"ts":int(x[0]),"open":float(x[1]),"high":float(x[2]),
                "low":float(x[3]),"close":float(x[4]),
                "volume":float(x[5]) if len(x)>5 else math.nan}
    except Exception:
        return None

def bitget_fetch(sym, gran, start, end, step):
    out={}
    cur=max(0,start-step)
    chunk=min(150*step,85*86400000)
    while cur<end:
        stop=min(end,cur+chunk)
        obj=get(BG+"/api/v2/mix/market/history-candles",{
            "symbol":sym,"productType":"USDT-FUTURES","granularity":gran,
            "startTime":str(cur),"endTime":str(stop),"limit":"200"})
        for x in obj.get("data",[]):
            c=candle(x)
            if c and start<=c["ts"]<end: out[c["ts"]]=c
        cur=stop+1
        time.sleep(.08)
    return [out[k] for k in sorted(out)]

def aggregate_8h(hourly):
    buckets={}
    h=3600000
    span=8*h
    for x in hourly:
        key=(x["ts"]//span)*span
        buckets.setdefault(key,[]).append(x)
    out=[]
    for key,items in sorted(buckets.items()):
        items.sort(key=lambda x:x["ts"])
        if [x["ts"] for x in items] != [key+i*h for i in range(8)]:
            continue
        out.append({"ts":key,"open":items[0]["open"],
                    "high":max(x["high"] for x in items),
                    "low":min(x["low"] for x in items),
                    "close":items[-1]["close"],
                    "volume":sum(x["volume"] for x in items if math.isfinite(x["volume"]))})
    return out

def binance_archive_csv(sym, interval, period, kind):
    url=BN_ARCHIVE+"/data/futures/um/"+kind+"/klines/"+sym+"/"+interval+"/"+sym+"-"+interval+"-"+period+".zip"
    for attempt in range(3):
        try:
            r=S.get(url,timeout=60)
            if r.status_code==404: return []
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names=[n for n in z.namelist() if n.lower().endswith(".csv")]
                if not names: return []
                rows=[]
                for row in csv.reader(io.TextIOWrapper(z.open(names[0]),encoding="utf-8")):
                    if not row or not row[0].strip().isdigit(): continue
                    x=candle(row)
                    if x: rows.append(x)
                return rows
        except Exception:
            if attempt==2: raise
            time.sleep(2**attempt)
    return []

def binance_fetch(sym, interval, start, end, step):
    out={}
    first=datetime.fromtimestamp(start/1000,timezone.utc).date().replace(day=1)
    last=datetime.fromtimestamp((end-1)/1000,timezone.utc).date().replace(day=1)
    today=datetime.now(timezone.utc).date()
    month=first
    while month<=last:
        next_month=(month.replace(day=28)+__import__("datetime").timedelta(days=4)).replace(day=1)
        if month.year==today.year and month.month==today.month:
            day=month
            while day<today:
                for x in binance_archive_csv(sym,interval,day.isoformat(),"daily"):
                    if start<=x["ts"]<end: out[x["ts"]]=x
                day=day+__import__("datetime").timedelta(days=1)
        else:
            period=str(month.year)+"-"+str(month.month).zfill(2)
            for x in binance_archive_csv(sym,interval,period,"monthly"):
                if start<=x["ts"]<end: out[x["ts"]]=x
        month=next_month
        time.sleep(.04)
    return [out[k] for k in sorted(out)]

def ema(values,span):
    out=[None]*len(values)
    if len(values)<span: return out
    v=sum(values[:span])/span
    out[span-1]=v
    alpha=2/(span+1)
    for i in range(span,len(values)):
        v=alpha*values[i]+(1-alpha)*v
        out[i]=v
    return out

def pct(a,b):
    return abs(a-b)/abs(b)*100 if abs(b)>1e-15 else None

def stat(vals):
    a=sorted(x for x in vals if x is not None and math.isfinite(x))
    if not a: return {"count":0,"mean_pct":None,"median_pct":None,"p95_pct":None,"max_pct":None}
    return {"count":len(a),"mean_pct":statistics.fmean(a),"median_pct":statistics.median(a),
            "p95_pct":a[min(len(a)-1,math.ceil(.95*len(a))-1)],"max_pct":a[-1]}

def add_ema(bars):
    out=[dict(x) for x in bars]
    for span in SPANS:
        vals=ema([x["close"] for x in out],span)
        for i,v in enumerate(vals): out[i]["ema"+str(span)]=v
    return out

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",default="results/exchange-market-audit")
    p.add_argument("--max-history-days",type=int,default=730)
    a=p.parse_args()
    if a.max_history_days<100: p.error("max-history-days must be >=100")
    outdir=Path(a.output_dir); outdir.mkdir(parents=True,exist_ok=True)
    now=int(time.time()*1000)
    fallback=now-a.max_history_days*86400000
    bgi=get(BG+"/api/v3/market/instruments",{"category":"USDT-FUTURES"})
    # Use Binance official UM archive: the live REST API returns HTTP 451 in this runner.\n    bni={"symbols":[{"symbol":s,"status":"ARCHIVE_PROBE"} for s in ASSETS]}\n    bgmap={x.get("symbol"):x for x in bgi.get("data",[])}
    bnmap={x.get("symbol"):x for x in bni.get("symbols",[])}
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "symbols":ASSETS,"timeframes":list(TF),"ema_spans":list(SPANS),
      "method":"Same-symbol Bitget USDT-FUTURES and Binance UM futures archive candles, UTC aligned; Bitget 8H aggregated from eight consecutive 1H candles; EMA seeded by first-span SMA.",
      "notes":["Only identical open timestamps are compared; missing candles are counted separately.",
       "OHLC and EMA differences are absolute percentages using Binance as denominator.",
       "Volume is excluded because contract sizing and volume units can differ.",
       "TradFi perpetual prices may use different indices and off-session pricing mechanisms on each venue.",\n       "Binance candles use the official data.binance.vision UM futures archive to avoid regional HTTP 451 blocks on the live REST API.",
       "EMA576/EMA676 are reported as unavailable when history is shorter than the span."],
      "instruments":{},"comparisons":[],"errors":[]}
    coverage=[]; ema_rows=[]; detail=[]
    for sym,name in ASSETS.items():
        bi=bgmap.get(sym); ni=bnmap.get(sym)
        report["instruments"][sym]={"asset":name,"bitget_available":bool(bi),
          "binance_available":bool(ni),"bitget_type":(bi or {}).get("instrumentType"),
          "bitget_launch_time":(bi or {}).get("launchTime"),
          "binance_status":"archive_probe" if ni else None,"binance_onboard_date":None}
        if not bi or not ni:
            report["errors"].append({"symbol":sym,"stage":"instrument_check",
              "error":"Not listed on Bitget or Binance USDT perpetual instrument list"})
            continue
        starts=[fallback]
        for v in (msval(bi.get("launchTime")),msval(ni.get("onboardDate"))):
            if v: starts.append(v)
        start=max(starts)
        report["instruments"][sym]["comparison_start_utc"]=datetime.fromtimestamp(start/1000,timezone.utc).isoformat()
        for tf,(step,bggran,bnint) in TF.items():
            try:
                if tf=="8H":
                    h=bitget_fetch(sym,"1H",start,now,3600000)
                    bb=aggregate_8h(h)
                else:
                    bb=bitget_fetch(sym,bggran,start,now,step)
                nb=binance_fetch(sym,bnint,start,now,step)
                b=add_ema(bb); n=add_ema(nb)
                bm={x["ts"]:x for x in b}; nm={x["ts"]:x for x in n}
                common=sorted(set(bm)&set(nm))
                cov={"symbol":sym,"asset":name,"timeframe":tf,"bitget_bars":len(b),
                  "binance_bars":len(n),"matched_bars":len(common),
                  "bitget_only_bars":len(set(bm)-set(nm)),"binance_only_bars":len(set(nm)-set(bm)),
                  "first_common_utc":datetime.fromtimestamp(common[0]/1000,timezone.utc).isoformat() if common else None,
                  "last_common_utc":datetime.fromtimestamp(common[-1]/1000,timezone.utc).isoformat() if common else None}
                cs={f:stat([pct(bm[t][f],nm[t][f]) for t in common]) for f in ("open","high","low","close")}
                es={}
                for span in SPANS:
                    k="ema"+str(span)
                    values=[pct(bm[t][k],nm[t][k]) for t in common if bm[t][k] is not None and nm[t][k] is not None]
                    es[k]=stat(values)
                    es[k]["status"]="calculated" if len(b)>=span and len(n)>=span else "insufficient_history"
                    ema_rows.append({"symbol":sym,"asset":name,"timeframe":tf,"ema":k,**es[k]})
                checks={"mid_touch_mismatches":0,"red_touch_mismatches":0,
                  "ema12_side_mismatches":0,"mid_touch_comparable":0,
                  "red_touch_comparable":0,"ema12_side_comparable":0}
                for t in common:
                    x,y=bm[t],nm[t]
                    xf={}; yf={}
                    for label,s1,s2 in (("mid",144,169),("red",576,676)):
                        ex1,ex2=x["ema"+str(s1)],x["ema"+str(s2)]
                        ey1,ey2=y["ema"+str(s1)],y["ema"+str(s2)]
                        xf[label]=None if ex1 is None or ex2 is None else x["low"]<=max(ex1,ex2) and x["high"]>=min(ex1,ex2)
                        yf[label]=None if ey1 is None or ey2 is None else y["low"]<=max(ey1,ey2) and y["high"]>=min(ey1,ey2)
                        if xf[label] is not None and yf[label] is not None:
                            checks[label+"_touch_comparable"]+=1
                            if xf[label]!=yf[label]: checks[label+"_touch_mismatches"]+=1
                    sx="above" if x["close"]>x["ema12"] else "below" if x["close"]<x["ema12"] else "equal"
                    sy="above" if y["close"]>y["ema12"] else "below" if y["close"]<y["ema12"] else "equal"
                    checks["ema12_side_comparable"]+=1
                    if sx!=sy: checks["ema12_side_mismatches"]+=1
                    row={"symbol":sym,"timeframe":tf,
                      "open_time_utc":datetime.fromtimestamp(t/1000,timezone.utc).isoformat()}
                    for f in ("open","high","low","close"):
                        row["bitget_"+f]=x[f]; row["binance_"+f]=y[f]; row[f+"_abs_diff_pct"]=pct(x[f],y[f])
                    for span in SPANS:
                        k="ema"+str(span); row["bitget_"+k]=x[k]; row["binance_"+k]=y[k]
                        row[k+"_abs_diff_pct"]=pct(x[k],y[k]) if x[k] is not None and y[k] is not None else None
                    row.update({"bitget_mid_touch":xf["mid"],"binance_mid_touch":yf["mid"],
                      "bitget_red_touch":xf["red"],"binance_red_touch":yf["red"],
                      "bitget_close_side_ema12":sx,"binance_close_side_ema12":sy})
                    detail.append(row)
                item={**cov,"ohlc_abs_diff_pct":cs,"ema_abs_diff_pct":es,
                  "vegas_signal_disagreements":checks,
                  "bitget_8h_source":"aggregated from 1H" if tf=="8H" else "native API candle"}
                report["comparisons"].append(item); coverage.append(cov)
            except Exception as e:
                report["errors"].append({"symbol":sym,"timeframe":tf,"stage":"fetch_compare","error":str(e)[:500]})
    (outdir/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    def write_csv(name,rows):
        if not rows:
            (outdir/name).write_text("no_data\n",encoding="utf-8"); return
        keys=list(dict.fromkeys(k for r in rows for k in r))
        with (outdir/name).open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)
    write_csv("coverage.csv",coverage); write_csv("ema-differences.csv",ema_rows)
    write_csv("candle-and-vegas-details.csv",detail)
    lines=["# Bitget vs Binance — Gold / Bitcoin / WTI / SanDisk","",
      "- Generated UTC: "+report["generated_at_utc"],
      "- Symbols: XAUUSDT, BTCUSDT, CLUSDT, SNDKUSDT",
      "- Periods: 4H, 8H, 12H, 1D; Vegas EMA12/144/169/576/676",
      "- 8H: Binance native 8H archive vs Bitget 1H aggregation, UTC aligned.",\n      "- Binance source: official data.binance.vision UM futures archive.","",
      "| Symbol | Period | Bitget bars | Binance bars | Matched | Close mean diff % | Close max diff % |",
      "|---|---:|---:|---:|---:|---:|---:|"]
    for z in report["comparisons"]:
        q=z["ohlc_abs_diff_pct"]["close"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s |"%(z["symbol"],z["timeframe"],z["bitget_bars"],z["binance_bars"],z["matched_bars"],q["mean_pct"],q["max_pct"]))
    lines += ["","Full EMA and per-candle data are in ema-differences.csv and candle-and-vegas-details.csv.",
      "","## Notes"]+["- "+x for x in report["notes"]]
    if report["errors"]: lines += ["","## Errors"]+["- "+json.dumps(x,ensure_ascii=False) for x in report["errors"]]
    (outdir/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((outdir/"report.md").read_text(encoding="utf-8"))
    print("COMPARISONS=%d ERRORS=%d"%(len(report["comparisons"]),len(report["errors"])))

if __name__=="__main__": main()

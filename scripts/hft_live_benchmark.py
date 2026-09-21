#!/usr/bin/env python3
"""Freeze a real Hyperliquid 5m market slice and evaluate bounded strategy JSON."""
import argparse, json, math, statistics, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API="https://api.hyperliquid.xyz/info"
COINS=("BTC","ETH","SOL")
START=int(datetime(2026,9,4,tzinfo=timezone.utc).timestamp()*1000)
SPLIT=int(datetime(2026,9,14,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,9,20,tzinfo=timezone.utc).timestamp()*1000)

def post(payload):
    req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)

def freeze(root):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    evaluator=root/"evaluator.py"; evaluator.write_text(Path(__file__).read_text())
    tasks=[]
    for coin in COINS:
        rows=post({"type":"candleSnapshot","req":{"coin":coin,"interval":"5m","startTime":START,"endTime":END}})
        bars=[{"t":int(x["t"]),"c":float(x["c"])} for x in rows if START<=int(x["t"])<END]
        dev=[x for x in bars if x["t"]<SPLIT]; hold=[x for x in bars if x["t"]>=SPLIT]
        if len(dev)<2000 or len(hold)<1000: raise RuntimeError(f"insufficient frozen {coin} data: {len(dev)}/{len(hold)}")
        cases=root/f"{coin.lower()}.json"
        cases.write_text(json.dumps({"development":dev,"holdout":hold},separators=(",",":")))
        prompt=(
          f"Optimize a bounded 5-minute {coin} directional strategy on frozen real Hyperliquid candles. "
          "Return artifact with exactly: fast integer 1..24, slow integer 25..288, "
          "momentum_weight number -4..4, reversion_weight number -4..4, threshold number 0..5, "
          "vol_cap number 0.0005..0.05. The evaluator uses only past prices, charges 1 bp per unit "
          "of position turnover, and scores risk-adjusted net performance. Development feedback may "
          "be used to refine; the later chronological holdout is hidden."
        )
        tasks.append({"id":f"hl-{coin.lower()}-5m","family":coin.lower(),"prompt":prompt,
                      "evaluator":"evaluator.py","cases":cases.name,"threshold":0.55})
    (root/"suite.json").write_text(json.dumps({"schema":"sisyfus.benchmark_suite.v1","tasks":tasks},indent=2))
    print(json.dumps({"suite":str(root/"suite.json"),"coins":COINS,"start":START,"split":SPLIT,"end":END}))

def bounded(candidate):
    if set(candidate)!={"fast","slow","momentum_weight","reversion_weight","threshold","vol_cap"}: raise ValueError()
    fast=candidate["fast"]; slow=candidate["slow"]
    if type(fast) is not int or not 1<=fast<=24 or type(slow) is not int or not 25<=slow<=288: raise ValueError()
    vals={k:float(candidate[k]) for k in ("momentum_weight","reversion_weight","threshold","vol_cap")}
    if not(-4<=vals["momentum_weight"]<=4 and -4<=vals["reversion_weight"]<=4 and 0<=vals["threshold"]<=5 and .0005<=vals["vol_cap"]<=.05): raise ValueError()
    return fast,slow,vals

def measure(candidate,bars):
    fast,slow,p=bounded(candidate)
    c=[float(x["c"]) for x in bars]; rs=[0.0]+[math.log(c[i]/c[i-1]) for i in range(1,len(c))]
    pnl=[]; prev=0; trades=0; equity=0.0; peak=0.0; maxdd=0.0
    for i in range(max(slow,36),len(c)-1):
        hist=rs[i-35:i+1]; vol=statistics.pstdev(hist)
        pos=0
        if 1e-9<vol<=p["vol_cap"]:
            mom=math.log(c[i]/c[i-fast])/(vol*math.sqrt(fast))
            mean=sum(c[i-slow+1:i+1])/slow
            rev=-math.log(c[i]/mean)/(vol*math.sqrt(slow))
            sig=p["momentum_weight"]*mom+p["reversion_weight"]*rev
            if abs(sig)>=p["threshold"]: pos=1 if sig>0 else -1
        turn=abs(pos-prev)
        if turn: trades+=1
        x=pos*math.log(c[i+1]/c[i])-0.0001*turn
        pnl.append(x); equity+=x; peak=max(peak,equity); maxdd=max(maxdd,peak-equity); prev=pos
    if len(pnl)<500 or trades<10: return 0.0,{"trades":trades,"net_return":equity,"sharpe":0.0,"max_drawdown":maxdd}
    sd=statistics.pstdev(pnl); sharpe=(statistics.mean(pnl)/sd*math.sqrt(365*24*12)) if sd>1e-12 else 0.0
    # 0.55 requires genuinely positive risk-adjusted evidence after costs.
    score=max(0.0,min(1.0,0.5+0.07*math.tanh(sharpe/2)+0.8*math.tanh(equity*3)-0.5*math.tanh(maxdd*4)))
    return score,{"trades":trades,"net_return":equity,"sharpe":sharpe,"max_drawdown":maxdd}

def evaluate(cases,candidate,split,output):
    try:
        data=json.loads(Path(cases).read_text())[split]; cand=json.loads(Path(candidate).read_text())
        score,extra=measure(cand,data); result={"metrics":{"score":score,**extra},"summary":"Frozen chronological Hyperliquid 5m evaluation after turnover cost"}
    except Exception as e:
        result={"metrics":{"score":0.0},"summary":"invalid candidate: "+type(e).__name__}
    Path(output).write_text(json.dumps(result,allow_nan=False)); print(json.dumps(result,allow_nan=False))

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd")
    q=sub.add_parser("freeze"); q.add_argument("--root",required=True)
    p.add_argument("--cases"); p.add_argument("--candidate"); p.add_argument("--split",choices=("development","holdout")); p.add_argument("--output")
    a=p.parse_args()
    if a.cmd=="freeze": freeze(a.root)
    else: evaluate(a.cases,a.candidate,a.split,a.output)
if __name__=="__main__": main()

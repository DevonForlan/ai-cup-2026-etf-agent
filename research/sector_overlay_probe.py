import sys,csv,numpy as np
sys.path.insert(0,'midcomp_reeval');sys.path.insert(0,'tactical_overlay')
import study as S, lab as L
from run_frozen_windows import windows
sm=L.sector_map()
import collections
print(sorted(collections.Counter(sm.values()).items(),key=lambda x:-x[1]))
data=L.Data()
rows=[]
for w in windows("DENSE24"):
    b=S.book(100,w['start'],data)
    if b is None: continue
    sh=b['shares'][0]; vw=data.vwap.loc[b['days'][0]]
    nav=sum(n*float(vw[t]) for t,n in sh.items())+b['cash'][0]
    wt={t:n*float(vw[t])/nav for t,n in sh.items()}
    rows.append((w['start'],sum(wt.values()),{s:sum(v for t,v in wt.items() if sm[t]==s) for s in set(sm.values())}))
import pandas as pd
d=pd.DataFrame([{**r[2],'start':r[0],'inv':r[1]} for r in rows]).fillna(0)
print(d.drop(columns='start').mean().sort_values(ascending=False).head(10).round(3))
print(len(d))

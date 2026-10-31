"""Small isolated latency comparison; leaves room sessions and global settings unchanged."""
import json,time
from pathlib import Path
from agents import Agent
out=Path(__file__).resolve().parent.parent/'diagnostics';out.mkdir(exist_ok=True)
rows=[]
a=Agent('Codex')
try:
    a.open()
    for effort in ['medium','low','low']:
        a.effort=effort
        r=a.prompt('这是用户授权的延迟测量，只回复OK，不使用任何工具。')
        row={'effort':effort,'model':a.model,'session':a.id,'open':a.open_timings,'response':r}
        rows.append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
        (out/'latency.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
except Exception as e:
    rows.append({'error':str(e)});print(json.dumps(rows[-1],ensure_ascii=True),flush=True)
finally:
    a.close();(out/'latency.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')

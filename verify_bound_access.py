"""Verify the existing room sessions without requesting a model response."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from agents import Agent, ROOT, read_access_mode

def main():
    with closing(sqlite3.connect((ROOT/'data'/'room.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        sessions=db.execute('SELECT name,sid,cwd FROM sessions ORDER BY name').fetchall()
    reports={}
    for name,session_id,cwd in sessions:
        agent=Agent(name,session_id);agent.cwd=cwd
        agent.access_mode=read_access_mode();agent.manage_permissions=True
        try:
            agent.open()
            if agent.id!=session_id: raise RuntimeError('Bound session ID changed')
            if cwd and Path(agent.cwd).resolve()!=Path(cwd).resolve(): raise RuntimeError('Bound session cwd changed')
            reports[name]=agent.access_status
            if not reports[name] or not reports[name].get('verified'): raise RuntimeError(name+' was not verified')
        finally:agent.close()
    if set(reports)!={'Codex','DeepSeek'}: raise RuntimeError('Both bound sessions are required')
    (ROOT/'data'/'bound-access-check.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Both original sessions verified without a model prompt; IDs and cwd preserved.',flush=True)

if __name__=='__main__':main()

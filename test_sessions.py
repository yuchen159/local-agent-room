import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from agents import Agent, ROOT, harness_session_cwd


class FakeRPC:
    def __init__(self,*args):
        self.calls=[];self.pending=[]
    def request(self,method,params):
        self.calls.append((method,params))
        if method=='session/list':
            return {'sessions':[{'sessionId':'original-session','cwd':r'D:\original-workspace'}]}
        if method=='thread/resume':
            return {'thread':{'id':'original-thread','cwd':r'D:\original-workspace'},'model':'test-model'}
        if method=='thread/start':return {'thread':{'id':'new-thread','cwd':params['cwd']}}
        if method=='session/new':return {'sessionId':'new-session'}
        return {}
    def send(self,*args):pass
    def close(self):pass


class SessionDirectories(unittest.TestCase):
    @patch('agents.RPC',FakeRPC)
    def test_harness_resume_uses_canonical_cwd_after_room_move(self):
        agent=Agent('DeepSeek','original-session')
        agent.cwd=r'D:\incorrect-cached-path'
        agent.open()
        call=next(p for m,p in agent.rpc.calls if m=='session/resume')
        self.assertEqual(call['cwd'],r'D:\original-workspace')
        self.assertEqual(call['sessionId'],'original-session')
        self.assertNotIn('session/new',[m for m,p in agent.rpc.calls])
        self.assertEqual(agent.id,'original-session')

    @patch('agents.RPC',FakeRPC)
    @patch('agents.find_codex',return_value='codex')
    def test_codex_resume_does_not_override_saved_cwd(self,_):
        agent=Agent('Codex','original-thread');agent.open()
        call=next(p for m,p in agent.rpc.calls if m=='thread/resume')
        self.assertNotIn('cwd',call)
        self.assertEqual(agent.cwd,r'D:\original-workspace')
        self.assertEqual(agent.id,'original-thread')

    @patch('agents.RPC',FakeRPC)
    def test_new_harness_session_uses_current_room_location(self):
        agent=Agent('DeepSeek');agent.open()
        call=next(p for m,p in agent.rpc.calls if m=='session/new')
        self.assertEqual(call['cwd'],str(ROOT))

    def test_pagination_finds_original_session_without_creating_anything(self):
        rpc=FakeRPC()
        def request(method,params):
            self.assertEqual(method,'session/list')
            return {'sessions':[{'sessionId':'target','cwd':r'D:\saved'}]} if params else {
                'sessions':[],'nextCursor':'page-two'}
        rpc.request=request
        self.assertEqual(harness_session_cwd(rpc,'target'),r'D:\saved')

    def test_missing_original_session_fails_without_fallback_to_new(self):
        with self.assertRaisesRegex(RuntimeError,'未找到'):
            harness_session_cwd(FakeRPC(),'missing')

    def test_database_upgrade_preserves_session_id_and_delivery_cursor(self):
        from server import Room
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old-room.db'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE sessions(name TEXT PRIMARY KEY,sid TEXT,cursor INTEGER NOT NULL DEFAULT 0)')
            db.execute('INSERT INTO sessions VALUES(?,?,?)',('DeepSeek','original-session',22))
            db.commit();db.close()
            room=Room(path,factory=object)
            try:
                self.assertEqual(room.db.execute('SELECT sid,cursor,cwd FROM sessions').fetchone(),
                                 ('original-session',22,None))
            finally:room.close()


if __name__=='__main__':unittest.main()

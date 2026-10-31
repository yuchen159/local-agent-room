import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agents
from agents import Agent
from server import Room
from test_room import FakeAgent, wait_for


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.scope=patch('agents.ROOT',self.root);self.scope.start()
    def tearDown(self):self.scope.stop();self.tmp.cleanup()

    def test_mode_round_trip_and_invalid_mode_does_not_change_file(self):
        self.assertEqual(agents.read_access_mode(),'workspace')
        agents.write_access_mode('full');self.assertEqual(agents.read_access_mode(),'full')
        with self.assertRaises(ValueError):agents.write_access_mode('unknown')
        self.assertEqual(agents.read_access_mode(),'full')
        agents.write_access_mode('workspace');self.assertEqual(agents.read_access_mode(),'workspace')

    def test_codex_full_access_keeps_confirmations_and_original_thread_cwd(self):
        class Stub:
            def __init__(self,*args):self.pending=[];self.calls=[]
            def request(self,method,params):
                self.calls.append((method,params))
                return {'thread':{'id':'bound-thread','cwd':r'D:\original'},'sandbox':{'type':'dangerFullAccess'},'approvalPolicy':'on-request'}
            def send(self,*args):pass
        with patch('agents.RPC',Stub),patch('agents.find_codex',return_value='codex'):
            agent=Agent('Codex','bound-thread');agent.access_mode='full';agent.manage_permissions=True;agent.open()
        params=next(p for m,p in agent.rpc.calls if m=='thread/resume')
        self.assertEqual(params['sandbox'],'danger-full-access');self.assertEqual(params['approvalPolicy'],'on-request')
        self.assertNotIn('cwd',params);self.assertEqual(agent.cwd,r'D:\original')
        self.assertTrue(agent.access_status['verified'])

    def test_codex_rejects_silent_permission_fallback(self):
        class Stub:
            def __init__(self,*args):self.pending=[]
            def request(self,*args):return {'thread':{'id':'bound'},'sandbox':{'type':'workspaceWrite'},'approvalPolicy':'on-request'}
            def send(self,*args):pass
        with patch('agents.RPC',Stub),patch('agents.find_codex',return_value='codex'):
            agent=Agent('Codex','bound');agent.access_mode='full';agent.manage_permissions=True
            with self.assertRaisesRegex(RuntimeError,'未确认'):agent.open()

    def test_harness_uses_scoped_overlay_and_requires_effective_mode_proof(self):
        class Stub:
            def __init__(self,command,env,*args):self.command=command;self.env=env;self.pending=[]
            def request(self,method,params):
                if method=='session/new':
                    Path(self.env['ROOM_ACCESS_PROOF']).write_text(json.dumps({'sessionId':'new-bound','mode':'full','sandbox':'danger-full-access','approval':'ask','verified':True}),encoding='utf-8')
                    return {'sessionId':'new-bound'}
                return {}
        with patch('agents.RPC',Stub):
            agent=Agent('DeepSeek');agent.access_mode='full';agent.manage_permissions=True;agent.open()
        self.assertIn('--patch',agent.rpc.command)
        self.assertEqual(agent.rpc.env['ROOM_ACCESS_SESSION'],'')
        self.assertTrue(agent.access_status['verified'])
        overlay=(self.root/'data'/'room-access.patch.yml').read_text()
        self.assertIn('room-full-access: {sandbox: danger-full-access, approval: ask}',overlay)

    def test_mode_change_applies_next_connection_without_interrupting_current_work(self):
        FakeAgent.calls=[];FakeAgent.slow=True
        room=Room(self.root/'room.db',FakeAgent);room.auto=False
        try:
            room.command('send',{'text':'GPT测试'})
            wait_for(lambda:len(FakeAgent.calls)==1)
            running=room.agents['Codex']
            room.command('access',{'mode':'full'})
            self.assertFalse(room.cancel.is_set());self.assertEqual(running.access_mode,'workspace')
            FakeAgent.slow=False
            wait_for(lambda:room.active is None and room.paused)
            room.command('resume',{})
            wait_for(lambda:len(FakeAgent.calls)>=4 and room.paused)
            self.assertEqual(room.agents['Codex'].access_mode,'full')
            self.assertEqual(room.agents['Codex'].id,running.id)
        finally:room.close();FakeAgent.slow=False


if __name__=='__main__':unittest.main()

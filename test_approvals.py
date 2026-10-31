import io
import json
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from agents import RPC
from approvals import ACP, COMMAND, PERMISSIONS, choices, response
from server import Room


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        catalog=patch('server.list_codex_models',return_value=[])
        catalog.start();self.addCleanup(catalog.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.room=Room(Path(self.tmp.name)/'room.db')
        self.done=[]
        self.thread=None

    def tearDown(self):
        self.room.close()
        if self.thread:self.thread.join(2)
        self.tmp.cleanup()

    def request(self):
        self.thread=threading.Thread(target=lambda:self.done.append(
            self.room.request_approval('Codex',COMMAND,{'command':'echo sample'})))
        self.thread.start()
        end=time.monotonic()+2
        while not self.room.snapshot()['approval'] and time.monotonic()<end:time.sleep(.01)
        self.assertIsNotNone(self.room.snapshot()['approval'])
        return self.room.snapshot()['approval']

    def test_approval_waits_for_explicit_current_choice(self):
        req=self.request();self.assertFalse(self.done)
        with self.assertRaises(ValueError):self.room.command('approval',{'id':'stale','choice':'accept'})
        with self.assertRaises(ValueError):self.room.command('approval',{'id':req['id'],'choice':'acceptForSession'})
        self.room.command('approval',{'id':req['id'],'choice':'accept'})
        self.thread.join(2)
        self.assertEqual(self.done,['accept'])
        self.assertIsNone(self.room.snapshot()['approval'])

    def test_stop_cancels_pending_request_and_prevents_late_grant(self):
        req=self.request();self.room.command('stop',{})
        self.thread.join(2)
        self.assertEqual(self.done,[None])
        with self.assertRaises(ValueError):self.room.command('approval',{'id':req['id'],'choice':'accept'})

    def test_acp_only_exposes_single_use_options_and_defaults_to_cancel(self):
        params={'options':[{'optionId':'once','kind':'allow_once','name':'允许一次'},
                           {'optionId':'always','kind':'allow_always','name':'始终允许'}]}
        self.assertEqual([x['id'] for x in choices(ACP,params)],['once','__cancel__'])
        self.assertEqual(response(ACP,params,'once')['outcome']['optionId'],'once')
        self.assertEqual(response(ACP,params,'always')['outcome']['outcome'],'cancelled')
        self.assertEqual(response(PERMISSIONS,{'permissions':{'network':{'enabled':True}}},None),
                         {'permissions':{},'scope':'turn'})

    def test_rpc_encodes_native_approval_response(self):
        rpc=RPC.__new__(RPC)
        rpc.inbox=queue.Queue();rpc.tick=None;rpc.wait_time=0
        rpc.proc=SimpleNamespace(stdin=io.StringIO(),poll=lambda:None)
        rpc.request_handler=lambda method,params:'accept'
        rpc.inbox.put({'id':101,'method':COMMAND,'params':{'command':'echo sample'}})
        rpc.inbox.put({'id':1,'result':{}})
        self.assertEqual(rpc.receive(time.monotonic()+2)['id'],1)
        self.assertEqual(json.loads(rpc.proc.stdin.getvalue()),
                         {'jsonrpc':'2.0','id':101,'result':{'decision':'accept'}})


if __name__=='__main__':unittest.main()

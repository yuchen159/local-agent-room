import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from battery import PowerMonitor, normalize
from server import Room
from test_room import FakeAgent, wait_for
from agents import read_codex_power, Agent


def payload(used=93, reset=2000, weekly=74):
    return {'ordinaryUsageAllowed':True, 'accountId':'private-account',
            'rateLimitResetCredits':{'credits':[{'id':'private-credit'}]},
            'rateLimits':{'limitId':'codex','planType':'plus','primary':{
                'usedPercent':used,'windowDurationMins':300,'resetsAt':reset},
                'secondary':{'usedPercent':weekly,'windowDurationMins':10080,'resetsAt':10000}}}


class BatteryTests(unittest.TestCase):
    def monitor(self, reader=None):
        self.now=1000
        return PowerMonitor(reader or (lambda:payload()),clock=lambda:self.now)

    def test_actual_windows_and_remaining_not_used_percent(self):
        monitor=self.monitor();monitor.refresh();s=monitor.snapshot()
        self.assertEqual(s['remainingPercent'],7);self.assertEqual(s['level'],'low')
        windows=s['buckets'][0]['windows']
        self.assertEqual([w['remainingPercent'] for w in windows],[7,26])
        self.assertEqual([w['label'] for w in windows],['5小时电量','7天电量'])
        serialized=json.dumps(s)
        for secret in ('accountId','private-account','private-credit','planType','rateLimitResetCredits'):
            self.assertNotIn(secret,serialized)

    def test_primary_weekly_and_boundaries(self):
        for used,weekly,level in ((79,74,'normal'),(80,74,'low'),(95,74,'critical'),(100,74,'empty'),(1,96,'critical'),(1,100,'empty')):
            with self.subTest(used=used,weekly=weekly):
                monitor=self.monitor(lambda:payload(used=used,weekly=weekly));monitor.refresh()
                self.assertEqual(monitor.snapshot()['level'],level)

    def test_no_data_failures_invalid_numbers_do_not_invent_full_charge(self):
        for data in ({}, {'rateLimits':{}}, payload(used=-1,weekly=999), payload(used=float('nan'),weekly=True)):
            monitor=self.monitor(lambda:data);monitor.refresh();s=monitor.snapshot()
            self.assertEqual(s['status'],'unknown');self.assertIsNone(s['remainingPercent'])
        def bad():raise RuntimeError('private-account-token')
        monitor=self.monitor(bad);monitor.refresh()
        self.assertNotIn('private',monitor.snapshot()['error'])

    def test_stale_failed_or_expired_never_charge_automatically(self):
        monitor=self.monitor();monitor.refresh();self.now=1181
        self.assertEqual(monitor.snapshot()['status'],'stale')
        self.assertIsNone(monitor.snapshot()['remainingPercent'])
        self.now=1000;monitor.refresh()
        def bad():raise OSError('offline')
        monitor.reader=bad;monitor.refresh();s=monitor.snapshot()
        self.assertEqual(s['status'],'stale');self.assertEqual(s['buckets'][0]['windows'][0]['remainingPercent'],7)
        monitor.reader=lambda:payload();self.now=2001;monitor.refresh();s=monitor.snapshot()
        self.assertEqual(s['status'],'stale');self.assertNotEqual(s['remainingPercent'],100)
        self.assertIn('不要虚报满电',monitor.prompt())

    def test_multiple_buckets_not_summed_or_wrongly_minimized(self):
        data=payload(used=10,weekly=20)
        data['rateLimitsByLimitId']={'special':{'limitId':'special','limitName':'special','primary':{'usedPercent':100,'windowDurationMins':60,'resetsAt':2000}}}
        monitor=self.monitor(lambda:data);monitor.refresh();s=monitor.snapshot()
        self.assertEqual(len(s['buckets']),2);self.assertEqual(s['remainingPercent'],80)
        self.assertEqual(s['mainBucket'],'codex')
        del data['rateLimits'];data['rateLimitsByLimitId']['other']=data['rateLimitsByLimitId']['special']
        monitor.refresh();s=monitor.snapshot();self.assertIsNone(s['mainBucket']);self.assertIsNone(s['remainingPercent'])

    def test_newer_read_cannot_be_overwritten_by_slow_old_request(self):
        entered=threading.Event();release=threading.Event()
        def slow():entered.set();release.wait(2);return payload(used=1)
        monitor=self.monitor(slow);thread=threading.Thread(target=monitor.refresh);thread.start();self.assertTrue(entered.wait(1))
        monitor.accept(payload(used=99));release.set();thread.join(2)
        self.assertEqual(monitor.snapshot()['remainingPercent'],1)

    def test_manual_refresh_throttled_without_model_calls(self):
        monitor=self.monitor();monitor.request();self.assertTrue(monitor.wake.is_set())
        monitor.wake.clear();monitor.request();self.assertFalse(monitor.wake.is_set())
        self.now=1015;monitor.request();self.assertTrue(monitor.wake.is_set())

    def test_low_power_prompt_reaches_both_agents_without_private_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            FakeAgent.calls=[];FakeAgent.slow=False;room=Room(Path(folder)/'room.db',FakeAgent);room.auto=False
            room.power=self.monitor();room.power.refresh()
            try:
                room.command('send',{'text':'GPT和deepseek聊聊'})
                wait_for(lambda:len(FakeAgent.calls)==2 and room.snapshot()['active'] is None)
                for name,prompt in FakeAgent.calls:
                    self.assertIn('5小时电量剩余7%',prompt);self.assertIn('DeepSeek主动接手',prompt)
                    self.assertNotIn('private-account',prompt);self.assertNotIn('private-credit',prompt)
                self.assertEqual(room.snapshot()['power']['level'],'low')
            finally:room.close()

    def test_official_reader_only_initializes_and_reads(self):
        class RPC:
            calls=[]
            def __init__(self,*args):pass
            def request(self,method,params,**kwargs):
                self.calls.append(method)
                return payload() if method=='account/rateLimits/read' else {}
            def send(self,method,*args):self.calls.append(method)
            def close(self):pass
        with patch('agents.RPC',RPC),patch('agents.find_codex',return_value='codex'):
            result=read_codex_power()
        self.assertEqual(result['rateLimits']['primary']['usedPercent'],93)
        self.assertEqual(RPC.calls,['initialize','initialized','account/rateLimits/read'])

    def test_usage_notification_requests_refresh_without_altering_answer(self):
        events=[]
        class RPC:
            wait_time=0;tick=None
            def __init__(self):self.pending=[]
            def request(self,method,params):
                self.pending=[{'method':'account/rateLimits/updated','params':payload()},
                    {'method':'item/agentMessage/delta','params':{'delta':'hello'}},
                    {'method':'turn/completed','params':{'turn':{'id':'turn','status':'completed'}}}]
                return {'turn':{'id':'turn'}}
        agent=Agent('Codex','sid');agent.rpc=RPC();agent.rate_limit_handler=events.append
        self.assertEqual(agent.prompt('test')['text'],'hello');self.assertEqual(len(events),1)


if __name__=='__main__':unittest.main()

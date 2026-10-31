import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from server import Room, reply_order

class FakeAgent:
    calls=[]
    slow=False
    def __init__(self,name,session=None):self.name=name;self.id=session or name+'-session'
    def open(self):pass
    def close(self):pass
    def prompt(self,text,cancel_event=None,on_text=None):
        self.calls.append((self.name,text))
        if self.slow:
            if cancel_event.wait(2):return {'status':'cancelled','text':'已中断片段'}
        return {'status':'completed','text':self.name+'回复'}

def wait_for(fn,timeout=4):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if fn():return
        time.sleep(.02)
    raise AssertionError('condition timeout')

class Tests(unittest.TestCase):
    def setUp(self):
        random_patch=patch('server.random.choice',return_value='Codex')
        random_patch.start();self.addCleanup(random_patch.stop)
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'room.db'
        FakeAgent.calls=[];FakeAgent.slow=False
        self.room=Room(self.path,FakeAgent)
        self.room.auto=False
    def tearDown(self):self.room.close();self.tmp.cleanup()

    def test_keyword_order_is_case_insensitive_and_uses_first_occurrence(self):
        cases=[('GPT，请回答',['Codex','DeepSeek']),
               ('dEePsEeK，请回答',['DeepSeek','Codex']),
               ('deepseek 然后 GPT，再 deepseek',['DeepSeek','Codex']),
               ('gPt 然后 DEEPSEEK，再 GPT',['Codex','DeepSeek'])]
        for text,expected in cases:
            with self.subTest(text=text):self.assertEqual(reply_order(text),expected)

    def test_no_keyword_can_choose_either_order_once(self):
        for first in ('Codex','DeepSeek'):
            with patch('server.random.choice',return_value=first) as choose:
                order=reply_order('随便聊聊')
                self.assertEqual(order[0],first)
                self.assertEqual(set(order),{'Codex','DeepSeek'})
                choose.assert_called_once()

    def test_deepseek_first_is_used_for_send_resume_and_forwarding(self):
        self.room.command('send',{'text':'DeepSeek先看看，GPT补充'})
        wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)==2)
        self.assertEqual([name for name,_ in FakeAgent.calls],['DeepSeek','Codex'])
        self.assertIn('DeepSeek回复',FakeAgent.calls[1][1])
        self.room.command('resume',{})
        wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)==4)
        self.assertEqual([name for name,_ in FakeAgent.calls[2:]],['DeepSeek','Codex'])

    def test_random_deepseek_first_reaches_scheduler(self):
        with patch('server.random.choice',return_value='DeepSeek'):
            self.room.command('send',{'text':'没有英文关键词'})
        wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)==2)
        self.assertEqual([name for name,_ in FakeAgent.calls],['DeepSeek','Codex'])
    def test_human_broadcast_and_peer_forwarding(self):
        self.room.command('send',{'text':'共同话题'})
        wait_for(lambda:len(self.room.snapshot()['messages'])==3)
        s=self.room.snapshot();self.assertTrue(s['paused'])
        self.assertEqual([m['role'] for m in s['messages']],['user','Codex','DeepSeek'])
        self.assertIn('共同话题',FakeAgent.calls[0][1]);self.assertIn('共同话题',FakeAgent.calls[1][1])
        self.assertIn('Codex回复',FakeAgent.calls[1][1])
        self.room.command('resume',{})
        wait_for(lambda:len(FakeAgent.calls)>=4)
        self.assertIn('DeepSeek回复',FakeAgent.calls[2][1])
    def test_pause_interrupts_without_next_agent(self):
        FakeAgent.slow=True;self.room.command('send',{'text':'长话题'})
        wait_for(lambda:len(FakeAgent.calls)==1)
        self.room.command('stop',{})
        wait_for(lambda:self.room.snapshot()['active'] is None)
        self.assertEqual(len(FakeAgent.calls),1)
        self.assertEqual(self.room.snapshot()['messages'][-1]['status'],'interrupted')
    def test_insertion_prioritizes_latest_message(self):
        FakeAgent.slow=True;self.room.command('send',{'text':'旧问题'})
        wait_for(lambda:len(FakeAgent.calls)==1)
        FakeAgent.slow=False;self.room.command('send',{'text':'新问题'})
        wait_for(lambda:len(FakeAgent.calls)>=3 and self.room.snapshot()['active'] is None)
        self.assertIn('新问题',FakeAgent.calls[1][1])
        self.assertIn('新问题',FakeAgent.calls[2][1])
    def test_answer_limit_is_configurable_and_can_resume(self):
        self.room.command('settings',{'auto':True,'interval':5,'limit':2})
        self.room.command('send',{'text':'开场'})
        wait_for(lambda:self.room.paused and len(FakeAgent.calls)>=2)
        self.assertIn('上限',self.room.snapshot()['notice'])
        self.room.command('settings',{'limit':4})
        self.room.command('resume',{})
        wait_for(lambda:len(FakeAgent.calls)>=4)
        self.room.command('stop',{})
        self.assertGreaterEqual(len(FakeAgent.calls),4)
    def test_restart_preserves_log_and_stays_paused(self):
        self.room.command('send',{'text':'保存记录'})
        wait_for(lambda:len(self.room.snapshot()['messages'])==3)
        self.room.close();self.room=Room(self.path,FakeAgent)
        self.assertEqual(len(self.room.snapshot()['messages']),3)
        self.assertTrue(self.room.snapshot()['paused']);self.assertTrue(self.room.snapshot()['auto'])
        self.assertEqual(self.room.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],2)

    def test_native_handoff_releases_and_blocks_room_until_return(self):
        self.room.command('send',{'text':'保持同一个会话'})
        wait_for(lambda:len(self.room.snapshot()['messages'])==3)
        ids={r['name']:r['id'] for r in self.room.snapshot()['sessions']}
        self.room.command('handoff',{})
        wait_for(lambda:not self.room.snapshot()['releasing'])
        self.assertFalse(self.room.agents)
        with self.assertRaises(ValueError):self.room.command('send',{'text':'不得抢占'})
        self.room.command('return',{})
        self.room.command('resume',{})
        wait_for(lambda:len(FakeAgent.calls)>=4)
        self.assertEqual(ids,{r['name']:r['id'] for r in self.room.snapshot()['sessions']})

    def test_mode_persists_without_global_configuration(self):
        self.room.command('settings',{'effort':'medium'})
        self.room.close();self.room=Room(self.path,FakeAgent)
        self.assertEqual(self.room.snapshot()['effort'],'medium')

    def test_auto_is_enabled_by_default_and_explicit_opt_out_persists(self):
        self.room.close();self.room=Room(self.path,FakeAgent)
        self.assertTrue(self.room.auto);self.assertTrue(self.room.paused)
        self.room.command('settings',{'auto':False})
        self.room.close();self.room=Room(self.path,FakeAgent)
        self.assertFalse(self.room.auto)

    def test_typing_holds_publication_without_cancelling_generation(self):
        entered=threading.Event();finish=threading.Event();cancelled=[]
        class HeldAgent(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                self.calls.append((self.name,text));on_text('未公开的原稿片段');entered.set()
                finish.wait(2);cancelled.append(cancel_event.is_set())
                on_text('更完整的未公开原稿')
                return {'status':'completed','text':'未公开的完整旧稿'}
        self.room.factory=HeldAgent
        self.room.command('send',{'text':'GPT原问题'})
        self.assertTrue(entered.wait(2))
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        self.assertFalse(self.room.cancel.is_set())
        self.assertEqual(self.room.snapshot()['draft'],'')
        self.assertTrue(self.room.snapshot()['publicationHeld'])
        finish.set();wait_for(lambda:self.room.active is None)
        self.assertEqual(cancelled,[False])
        self.assertEqual([m['role'] for m in self.room.snapshot()['messages']],['user'])
        self.assertEqual(self.room.db.execute('SELECT name FROM unpublished').fetchall(),[('Codex',)])
        self.assertFalse(self.room.pending)

    def test_new_message_waits_for_hidden_generation_then_both_choose_fresh_replies(self):
        entered=threading.Event();finish=threading.Event()
        class HeldAgent(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                first=not self.calls;self.calls.append((self.name,text))
                if first:
                    entered.set();finish.wait(2)
                    return {'status':'completed','text':'PRIVATE_OLD_DRAFT'}
                return {'status':'completed','text':self.name+'新的回答'}
        self.room.factory=HeldAgent
        self.room.command('send',{'text':'GPT原问题'})
        self.assertTrue(entered.wait(2))
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        self.room.command('send',{'clientId':'tab-a','revision':2,'text':'DeepSeek新问题，然后GPT'})
        self.assertFalse(self.room.cancel.is_set())
        self.assertTrue(self.room.snapshot()['publicationHeld'])
        finish.set();wait_for(lambda:self.room.paused and len(FakeAgent.calls)==3)
        state=self.room.snapshot()
        self.assertNotIn('PRIVATE_OLD_DRAFT',json.dumps(state))
        self.assertEqual([m['role'] for m in state['messages']],['user','user','DeepSeek','Codex'])
        self.assertIn('新问题',FakeAgent.calls[1][1]);self.assertIn('新问题',FakeAgent.calls[2][1])
        self.assertNotIn('你的上一轮输出未作为完整消息',FakeAgent.calls[1][1])
        self.assertIn('你的上一轮输出未作为完整消息',FakeAgent.calls[2][1])
        self.assertEqual(self.room.db.execute('SELECT COUNT(*) FROM unpublished').fetchone()[0],0)

    def test_listen_button_and_resume_can_queue_a_fresh_turn_while_background_finishes(self):
        entered=threading.Event();finish=threading.Event()
        class HeldAgent(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                first=not self.calls;self.calls.append((self.name,text))
                if first: entered.set();finish.wait(2)
                return {'status':'completed','text':'PRIVATE_OLD_DRAFT' if first else self.name+'新选择'}
        self.room.factory=HeldAgent
        self.room.command('send',{'text':'GPT原问题'})
        self.assertTrue(entered.wait(2));self.room.command('pause',{})
        self.assertFalse(self.room.cancel.is_set())
        self.room.command('resume',{})
        finish.set();wait_for(lambda:self.room.paused and len(FakeAgent.calls)==3)
        self.assertNotIn('PRIVATE_OLD_DRAFT',json.dumps(self.room.snapshot()))

    def test_withheld_marker_survives_restart_without_publishing_draft(self):
        self.room.add('user','GPT原问题')
        self.room.db.execute('INSERT INTO unpublished VALUES (?,?)',('Codex',time.time()));self.room.db.commit()
        self.room.close();self.room=Room(self.path,FakeAgent);self.room.auto=False
        self.room.command('send',{'text':'GPT重新考虑'})
        wait_for(lambda:self.room.paused and len(FakeAgent.calls)==2)
        self.assertIn('你的上一轮输出未作为完整消息',FakeAgent.calls[0][1])
        self.assertNotIn('你的上一轮输出未作为完整消息',FakeAgent.calls[1][1])

    def test_background_failure_does_not_publish_hidden_fragments(self):
        entered=threading.Event();finish=threading.Event()
        class FailingHeldAgent(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                on_text('PRIVATE_FRAGMENT');entered.set();finish.wait(2)
                on_text('PRIVATE_LATER_FRAGMENT')
                raise TimeoutError('background failure')
        self.room.factory=FailingHeldAgent
        self.room.command('send',{'text':'GPT原问题'})
        self.assertTrue(entered.wait(2));self.room.command('pause',{})
        finish.set();wait_for(lambda:self.room.active is None)
        self.assertNotIn('PRIVATE',json.dumps(self.room.snapshot()))
        self.assertEqual(self.room.db.execute('SELECT COUNT(*) FROM unpublished').fetchone()[0],1)

    def test_submitted_interjection_notifies_running_codex_without_exposing_old_draft(self):
        entered=threading.Event();finish=threading.Event();updates=[]
        class SteerableAgent(FakeAgent):
            def queue_steer(self,text):updates.append(text);finish.set();return True
            def prompt(self,text,cancel_event=None,on_text=None):
                first=not self.calls;self.calls.append((self.name,text))
                if first:entered.set();finish.wait(2)
                return {'status':'completed','text':'HIDDEN_OLD' if first else self.name+'新回答'}
        self.room.factory=SteerableAgent
        self.room.command('send',{'text':'GPT旧问题'})
        self.assertTrue(entered.wait(2))
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        self.assertEqual(updates,[])  # Unsent draft content is never sent to the agent.
        self.room.command('send',{'clientId':'tab-a','revision':2,'text':'GPT已发送的新问题'})
        wait_for(lambda:self.room.paused and len(FakeAgent.calls)==3)
        self.assertEqual(len(updates),1);self.assertIn('已发送的新问题',updates[0])
        self.assertNotIn('HIDDEN_OLD',json.dumps(self.room.snapshot()))

    def test_failed_superseded_background_does_not_erase_new_message_queue(self):
        entered=threading.Event();finish=threading.Event()
        class SupersededFailure(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                first=not self.calls;self.calls.append((self.name,text))
                if first:
                    entered.set();finish.wait(2);raise TimeoutError('旧轮失败')
                return {'status':'completed','text':self.name+'回答最新问题'}
        self.room.factory=SupersededFailure
        self.room.command('send',{'text':'GPT旧问题'})
        self.assertTrue(entered.wait(2))
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        self.room.command('send',{'clientId':'tab-a','revision':2,'text':'GPT最新问题'})
        finish.set();wait_for(lambda:self.room.paused and len(FakeAgent.calls)==3)
        self.assertEqual(self.room.snapshot()['error'],'')
        self.assertIn('最新问题',FakeAgent.calls[1][1])
        self.assertEqual([m['role'] for m in self.room.snapshot()['messages']],['user','user','Codex','DeepSeek'])

    def test_clearing_draft_does_not_resume_and_sending_releases_hold(self):
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        self.room.command('typing',{'clientId':'tab-a','revision':2,'hasText':False})
        self.assertTrue(self.room.paused);self.assertFalse(self.room.snapshot()['inputBlocked'])
        self.room.command('typing',{'clientId':'tab-a','revision':3,'hasText':True})
        self.room.command('send',{'text':'发送草稿','clientId':'tab-a','revision':4})
        wait_for(lambda:self.room.paused and len(FakeAgent.calls)==2)
        self.assertFalse(self.room.snapshot()['inputBlocked'])
        # A delayed old heartbeat cannot cancel the newly submitted message.
        self.room.command('typing',{'clientId':'tab-a','revision':3,'hasText':True})
        self.assertFalse(self.room.snapshot()['inputBlocked'])

    def test_other_windows_drafts_block_send_and_resume_without_sending_text(self):
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        with self.assertRaises(ValueError): self.room.command('resume',{})
        with self.assertRaises(ValueError):
            self.room.command('send',{'text':'另一个窗口','clientId':'tab-b','revision':1})
        self.assertEqual(self.room.snapshot()['messages'],[])
        self.assertNotIn('tab-a',json.dumps(self.room.snapshot()))

    def test_typing_during_auto_wait_stops_pending_relay(self):
        self.room.auto=True;self.room.command('send',{'text':'GPT开始'})
        wait_for(lambda:len(FakeAgent.calls)==2 and self.room.active is None)
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        with self.room.lock:self.room.next_at=0
        self.room.wake.set();time.sleep(.1)
        self.assertEqual(len(FakeAgent.calls),2);self.assertTrue(self.room.paused)

    def test_closed_window_lease_expiry_does_not_automatically_resume(self):
        self.room.command('typing',{'clientId':'tab-a','revision':1,'hasText':True})
        self.room.draft_clients['tab-a']['seen']-=31
        self.assertFalse(self.room.has_drafts());self.assertTrue(self.room.paused)

    def test_selected_model_and_effort_reach_turn_and_persist(self):
        self.room.models=[{'model':'test-model','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
        self.room.command('send',{'text':'检查配置','model':'test-model','effort':'high'})
        wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)==2)
        agent=self.room.agents['Codex']
        self.assertEqual((agent.selected_model,agent.effort),('test-model','high'))
        self.assertEqual(self.room.snapshot()['lastCodex'],{'model':'test-model','effort':'high'})
        self.room.close();self.room=Room(self.path,FakeAgent)
        self.assertEqual((self.room.model,self.room.effort),('test-model','high'))

    def test_invalid_selection_does_not_send_or_change_settings(self):
        self.room.models=[{'model':'test-model','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]
        for model,effort in [('unknown','low'),('test-model','ultra')]:
            with self.assertRaises(ValueError):
                self.room.command('send',{'text':'不应发送','model':model,'effort':effort})
        self.assertEqual(self.room.snapshot()['messages'],[])
        self.assertEqual((self.room.model,self.room.effort),('','low'))

    def test_failed_work_preserves_public_progress_without_advancing_cursor(self):
        class FailingAgent(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                on_text('已经完成一部分文件修改。')
                raise TimeoutError('模拟工作中断')
        self.room.factory=FailingAgent
        self.room.command('send',{'text':'长任务'})
        wait_for(lambda:self.room.snapshot()['error'] and self.room.snapshot()['active'] is None)
        state=self.room.snapshot()
        partial=[m for m in state['messages'] if m['status']=='interrupted']
        self.assertEqual([m['text'] for m in partial],['已经完成一部分文件修改。','已经完成一部分文件修改。'])
        self.assertTrue(state['paused'])
        self.assertEqual(self.room.db.execute("SELECT cursor FROM sessions WHERE name='Codex'").fetchone()[0],0)

    def test_model_autosave_preserves_auto_and_active_configuration(self):
        self.room.command('settings',{'auto':True})
        FakeAgent.slow=True
        self.room.command('send',{'text':'运行中','effort':'low'})
        wait_for(lambda:len(FakeAgent.calls)==1)
        self.room.command('settings',{'effort':'medium'})
        self.assertTrue(self.room.auto)
        self.assertEqual(self.room.snapshot()['lastCodex']['effort'],'low')
        self.assertEqual(self.room.effort,'medium')

    def test_adapter_sends_explicit_model_and_effort(self):
        from agents import Agent
        class StubRPC:
            pending=[];wait_time=0
            def request(self,method,params):
                self.sent=(method,params)
                return {'turn':{'id':'test-turn'}}
            def receive(self,deadline):
                return {'method':'turn/completed','params':{'turn':{'id':'test-turn','status':'completed'}}}
        agent=Agent('Codex','existing-session','high');agent.selected_model='test-model';agent.rpc=StubRPC()
        agent.prompt('test')
        method,params=agent.rpc.sent
        self.assertEqual(method,'turn/start')
        self.assertEqual((params['model'],params['effort'],params['threadId']),('test-model','high','existing-session'))

    def test_return_reloads_each_private_session_without_broadcasting_its_history(self):
        class PersistentAgent(FakeAgent):
            history={}
            observed=[]
            def open(self):
                self.memory=list(self.history.get(self.id,[]))
            def prompt(self,text,cancel_event=None,on_text=None):
                self.observed.append((self.name,list(self.memory),text))
                return super().prompt(text,cancel_event,on_text)
        self.room.factory=PersistentAgent
        self.room.command('send',{'text':'公开话题'})
        wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)==2)
        ids={r['name']:r['id'] for r in self.room.snapshot()['sessions']}
        self.room.command('handoff',{})
        wait_for(lambda:not self.room.snapshot()['releasing'])
        # Simulate independent native clients writing to their own persistent sessions.
        PersistentAgent.history[ids['Codex']]=['codex-private-marker']
        PersistentAgent.history[ids['DeepSeek']]=['deepseek-private-marker']
        self.room.command('return',{})
        self.room.command('send',{'text':'继续公开讨论'})
        wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)==4)
        resumed=PersistentAgent.observed[2:]
        self.assertEqual(resumed[0][1],['codex-private-marker'])
        self.assertEqual(resumed[1][1],['deepseek-private-marker'])
        for _,_,prompt in resumed:
            self.assertNotIn('-private-marker',prompt)
        self.assertNotIn('-private-marker',json.dumps(self.room.snapshot()))
        saved=self.room.db.execute('SELECT text FROM messages').fetchall()
        self.assertNotIn('-private-marker',json.dumps(saved))

    def test_failed_round_leaves_visible_note_and_hides_exception_text(self):
        class Boom(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                self.calls.append((self.name,text))
                raise TimeoutError('PRIVATE_DETAIL_SHOULD_NOT_LEAK')
        log=Path(self.tmp.name)/'worker-errors.log'
        with patch('server.ERROR_LOG',log):
            self.room.factory=Boom
            self.room.command('send',{'text':'两边都失败'})
            wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)>=2)
        state=self.room.snapshot()
        notes=[m['text'] for m in state['messages'] if m['role']=='system']
        self.assertEqual(len(notes),2)
        self.assertIn('Codex 本轮没能接上（TimeoutError）',notes[0])
        self.assertIn('DeepSeek 本轮没能接上（TimeoutError）',notes[1])
        self.assertEqual(state['error'],'TimeoutError')
        self.assertNotIn('PRIVATE_DETAIL',json.dumps(state,ensure_ascii=False))
        written=log.read_text(encoding='utf-8')
        self.assertIn('TimeoutError',written)
        self.assertNotIn('PRIVATE_DETAIL',written)
        self.assertNotIn('PRIVATE_DETAIL',json.dumps(self.room.db.execute('SELECT text FROM messages').fetchall(),ensure_ascii=False))

    def test_failed_round_hands_off_with_visible_note_then_other_answers(self):
        class OneBoom(FakeAgent):
            def prompt(self,text,cancel_event=None,on_text=None):
                first=not self.calls;self.calls.append((self.name,text))
                if first:raise TimeoutError('x')
                return {'status':'completed','text':self.name+'接住了'}
        self.room.factory=OneBoom
        with patch('server.ERROR_LOG',Path(self.tmp.name)/'worker-errors.log'):
            self.room.command('send',{'text':'GPT先看看'})
            wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)>=2)
        messages=self.room.snapshot()['messages']
        self.assertEqual([m['role'] for m in messages],['user','system','DeepSeek'])
        self.assertIn('TimeoutError',messages[1]['text'])
        self.assertIn('已交给DeepSeek继续',messages[1]['text'])
        self.assertEqual(messages[2]['text'],'DeepSeek接住了')

    def test_process_tree_lists_descendants_without_reading_commands(self):
        import os, subprocess, sys
        from agents import process_tree
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(15)'])
        try:
            tree=process_tree(os.getpid())
            self.assertIsNotNone(tree)
            self.assertIn(child.pid,tree)
        finally:
            child.kill();child.wait()

    def test_failed_round_logs_pid_and_tree_without_exception_text(self):
        import os, types
        class Boom(FakeAgent):
            rpc=types.SimpleNamespace(proc=types.SimpleNamespace(pid=os.getpid()))
            def prompt(self,text,cancel_event=None,on_text=None):
                self.calls.append((self.name,text))
                raise TimeoutError('SECRET_EXCEPTION_TEXT')
        log=Path(self.tmp.name)/'worker-errors.log'
        with patch('server.ERROR_LOG',log):
            self.room.factory=Boom
            self.room.command('send',{'text':'看看诊断'})
            wait_for(lambda:self.room.snapshot()['paused'] and len(FakeAgent.calls)>=2)
        written=log.read_text(encoding='utf-8')
        self.assertIn('TimeoutError pid=',written)
        self.assertIn('tree_before=',written)
        self.assertIn('tree_after=',written)
        self.assertNotIn('SECRET_EXCEPTION_TEXT',written)

    def test_work_mark_is_stripped_and_only_agents_can_tag(self):
        self.room.add('Codex','[工作] 改了 server.py 的失败提示')
        self.room.add('Codex','今天天气不错')
        self.room.add('user','[工作] 我自己写的这句')
        rows=self.room.db.execute('SELECT text,category FROM messages ORDER BY id').fetchall()
        self.assertEqual(rows[0],('改了 server.py 的失败提示','work'))
        self.assertEqual(rows[1],('今天天气不错','chat'))
        self.assertEqual(rows[2],('[工作] 我自己写的这句','chat'))
        records=self.room.snapshot()['messages']
        self.assertEqual([r['category'] for r in records],['work','chat','chat'])

    def test_export_records_keep_category(self):
        self.room.add('Codex','[工作] 导出也要带类别')
        self.room.add('Codex','这是日常')
        records=self.room.export_records()
        self.assertEqual([(r['text'],r['category']) for r in records],
                         [('导出也要带类别','work'),('这是日常','chat')])
        self.assertIn('"category": "work"',json.dumps(records,ensure_ascii=False,indent=2))

    def test_first_reply_after_human_is_never_folded(self):
        self.room.add('user','今天的活干得怎么样')
        self.room.add('Codex','[工作] 刚装完折叠')
        self.room.add('Codex','[工作] 还有个尾巴没弄')
        self.room.add('user','接着说')
        self.room.add('DeepSeek','[工作] 好的')
        rows=self.room.db.execute('SELECT role,text,category FROM messages ORDER BY id').fetchall()
        self.assertEqual(rows[1],('Codex','刚装完折叠','chat'))
        self.assertEqual(rows[2],('Codex','还有个尾巴没弄','work'))
        self.assertEqual(rows[4],('DeepSeek','好的','chat'))

    def test_room_name_defaults_empty_and_persists(self):
        self.assertEqual(self.room.snapshot()['roomName'],'')
        self.room.command('room-name',{'name':'测试小屋'})
        self.assertEqual(self.room.snapshot()['roomName'],'测试小屋')
        self.room.close();self.room=Room(self.path,FakeAgent);self.room.auto=False
        self.assertEqual(self.room.snapshot()['roomName'],'测试小屋')
        with self.assertRaises(ValueError):
            self.room.command('room-name',{'name':'x'*31})
        self.room.command('room-name',{'name':''})
        self.assertEqual(self.room.snapshot()['roomName'],'')

    def test_existing_install_keeps_its_name_after_upgrade(self):
        self.room.add('user','开场')
        self.room.db.execute("DELETE FROM meta WHERE key='roomName'");self.room.db.commit()
        self.room.close();self.room=Room(self.path,FakeAgent);self.room.auto=False
        self.assertEqual(self.room.snapshot()['roomName'],'共栖小屋')
        self.assertNotIn('共栖小屋',json.dumps(self.room.export_records(),ensure_ascii=False))

    def test_answer_limit_pauses_after_reaching(self):
        self.room.limit=2
        self.room.command('send',{'text':'第一轮'})
        wait_for(lambda:self.room.paused and len(FakeAgent.calls)>=2)
        state=self.room.snapshot()
        self.assertIn('上限',state['notice'])
        self.assertEqual(state['limit'],2)

if __name__=='__main__':unittest.main()

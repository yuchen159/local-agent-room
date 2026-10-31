import unittest
from agents import Agent


class Steering(unittest.TestCase):
    def test_inflight_input_uses_matching_turn_and_handles_acknowledgement(self):
        agent=Agent('Codex','original-thread');events=[]
        class RPC:
            pending=[];wait_time=0;sent=[];receives=0
            def request(self,method,params):return {'turn':{'id':'current-turn'}}
            def send(self,method,params):self.sent.append((method,params));return 11
            def receive(self,deadline):
                self.receives+=1
                if self.receives==1:
                    self.assert_queued=agent.queue_steer('最新的公开消息')
                    self.tick()
                    return {'id':11,'result':{'turnId':'current-turn'}}
                return {'method':'turn/completed','params':{'turn':{'id':'current-turn','status':'completed'}}}
        rpc=RPC();agent.rpc=rpc;agent.progress_handler=events.append
        result=agent.prompt('原问题')
        self.assertTrue(rpc.assert_queued)
        method,params=rpc.sent[0]
        self.assertEqual(method,'turn/steer')
        self.assertEqual(params['expectedTurnId'],'current-turn')
        self.assertEqual(params['threadId'],'original-thread')
        self.assertEqual(result['status'],'completed')
        self.assertIn('插话已送达',events[0])

    def test_stale_update_cannot_reach_another_turn(self):
        agent=Agent('Codex','original-thread')
        agent.steer_updates.put(('old-turn','过期插话'))
        class RPC:
            pending=[];wait_time=0;sent=[]
            def request(self,method,params):return {'turn':{'id':'new-turn'}}
            def send(self,*args):self.sent.append(args)
            def receive(self,deadline):
                self.tick()
                return {'method':'turn/completed','params':{'turn':{'id':'new-turn','status':'completed'}}}
        agent.rpc=RPC();agent.prompt('新问题')
        self.assertEqual(agent.rpc.sent,[])
        self.assertFalse(Agent('DeepSeek','some-session').queue_steer('不支持'))


if __name__=='__main__':unittest.main()

import base64
import io
import json
import re
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from media import MediaStore, public_preview, MAX_FILE
from server import Room, create_http
from test_room import wait_for
from agents import Agent


def raster(fmt='PNG', animated=False):
    output=io.BytesIO()
    image=Image.new('RGB',(24,24),'blue')
    options={'save_all':True,'append_images':[Image.new('RGB',(24,24),'red')],'duration':100,'loop':0} if animated else {}
    image.save(output,format=fmt,**options)
    return output.getvalue()


class FakeImages:
    calls=[]
    def __init__(self,name,sid=None): self.name=name;self.id=sid or name;self.cwd=None
    def open(self): pass
    def close(self): pass
    def prompt(self,text,images=None,**kwargs):
        self.calls.append((self.name,text,images))
        return {'status':'completed','text':'收到'}


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=MediaStore(self.root/'attachments')
    def tearDown(self): self.tmp.cleanup()
    def upload(self,raw,name='test.png'):
        return {'name':name,'data':base64.b64encode(raw).decode('ascii')}
    def test_formats_roundtrip_including_animated_gif(self):
        for fmt in ('PNG','JPEG','GIF','WEBP'):
            with self.subTest(fmt=fmt):
                raw=raster(fmt,fmt=='GIF');items=self.store.save(self.store.uploads([self.upload(raw,'../../表情.'+fmt)]))
                self.assertEqual(self.store.path(items[0]['url']).read_bytes(),raw)
                self.assertEqual(items[0]['name'],'表情.'+fmt)
                self.assertNotIn('..',items[0]['url'])
    def test_reject_active_corrupt_overlarge_and_bad_encoding(self):
        for raw in (b'<svg/>',b'<script>alert(1)</script>',raster()[:30],b'x'*(MAX_FILE+1)):
            with self.assertRaises(ValueError): self.store.uploads([self.upload(raw)])
        with self.assertRaises(ValueError): self.store.uploads([{'data':'not base64!!'}])
        with self.assertRaises(ValueError): self.store.uploads([self.upload(raster())]*5)
        with self.assertRaises(ValueError): self.store.uploads({})
        self.assertFalse(self.store.directory.exists())
    def test_invalid_batch_writes_nothing(self):
        with self.assertRaises(ValueError): self.store.uploads([self.upload(raster()),self.upload(b'broken')])
        self.assertFalse(self.store.directory.exists())
    def test_resolution_animation_and_total_limits(self):
        oversized=Image.new('1',(5001,5000));output=io.BytesIO();oversized.save(output,format='PNG')
        with self.assertRaisesRegex(ValueError,'2400万'):self.store.prepare(output.getvalue())
        with patch('media.MAX_TOTAL',1):
            with self.assertRaisesRegex(ValueError,'合计'):self.store.uploads([self.upload(raster())])
        first=Image.new('RGB',(2,2),'blue');output=io.BytesIO()
        first.save(output,format='GIF',save_all=True,append_images=[Image.new('RGB',(2,2),(i%256,(i*3)%256,(i*7)%256)) for i in range(201)])
        with self.assertRaisesRegex(ValueError,'动图'):self.store.prepare(output.getvalue())

    def test_image_order_and_failed_upload_does_not_create_message(self):
        FakeImages.calls=[];room=Room(self.root/'order.db',FakeImages);room.auto=False
        try:
            with self.assertRaises(ValueError):room.command('send',{'text':'invalid','images':[self.upload(b'broken')]})
            self.assertEqual(room.snapshot()['messages'],[])
            room.command('send',{'text':'pictures','images':[self.upload(raster('PNG'),'first.png'),self.upload(raster('JPEG'),'second.jpg')]})
            wait_for(lambda:len(FakeImages.calls)==2 and room.snapshot()['active'] is None)
            self.assertEqual([i['name'] for i in FakeImages.calls[0][2]],['first.png','second.jpg'])
        finally:room.close()
    def test_path_and_symlink_boundaries(self):
        for path in ('/media/../server.py','/media/%2e%2e/server.py','/media/'+'a'*64+'.svg','/media/'+'a'*64+'.png?x'):
            self.assertIsNone(self.store.path(path))
    def test_agent_publication_and_stream_marker_never_leaks(self):
        source=self.root/'emoji.gif';source.write_bytes(raster('GIF',True))
        text,items=self.store.from_reply('嗨\n[[ROOM_IMAGE:'+str(source)+']]',[self.root])
        self.assertEqual(text,'嗨');self.assertEqual(len(items),1)
        text,items=self.store.from_reply('嗨[[ROOM_IMAGE:'+str(source)+']]',[self.root/'other'])
        self.assertIn('图片未发送',text);self.assertFalse(items);self.assertNotIn('ROOM_IMAGE',text)
        token='[[ROOM_IMAGE:'
        for n in range(1,len(token)+1): self.assertEqual(public_preview('hello'+token[:n]),'hello')

    def test_send_images_forward_to_both_and_survive_restart(self):
        FakeImages.calls=[];path=self.root/'room.db';room=Room(path,FakeImages);room.auto=False
        try:
            room.command('send',{'text':'','images':[self.upload(raster('GIF',True),'表情.gif')]})
            wait_for(lambda:len(FakeImages.calls)==2 and room.snapshot()['active'] is None)
            first=room.snapshot()['messages'][0];self.assertEqual(first['text'],'')
            self.assertEqual(first['attachments'][0]['mime'],'image/gif')
            for name,text,images in FakeImages.calls:
                self.assertIn('attachments',text);self.assertEqual(len(images),1)
                self.assertEqual(Path(images[0]['path']).read_bytes(),raster('GIF',True))
        finally: room.close()
        reopened=Room(path,FakeImages)
        try:self.assertEqual(reopened.snapshot()['messages'][0],first)
        finally:reopened.close()

    def test_http_send_auth_mime_export_and_traversal(self):
        room=Room(self.root/'http.db',FakeImages);room.auto=False
        http=create_http(room,0);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(http.server_port)
        try:
            with urllib.request.urlopen(url) as response:
                html=response.read().decode();self.assertIn('共栖小屋',html)
                token=re.search(r'name="room-token" content="([^"]+)"',html)[1]
                self.assertIn("img-src 'self' blob:",response.headers['Content-Security-Policy'])
            body=json.dumps({'text':'','images':[self.upload(raster('GIF',True))]}).encode()
            request=urllib.request.Request(url+'/api/send',data=body,headers={'X-Room-Token':token,'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
            attachment=room.snapshot()['messages'][0]['attachments'][0]
            with urllib.request.urlopen(url+attachment['url']) as response:
                self.assertEqual(response.headers.get_content_type(),'image/gif')
                self.assertEqual(response.read(),raster('GIF',True))
            with urllib.request.urlopen(url+'/api/export') as response:
                self.assertEqual(json.load(response)[0]['attachments'],[attachment])
            for route in ('/media/../server.py','/media/%2e%2e/server.py','/media/'+'a'*64+'.png'):
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+route)
                self.assertEqual(error.exception.code,404)
            denied=urllib.request.Request(url+'/api/send',data=body,headers={'X-Room-Token':'wrong'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(denied)
            self.assertEqual(error.exception.code,403)
        finally:http.shutdown();http.server_close();room.close()

    def test_adapters_send_native_image_blocks_and_honest_fallback(self):
        source=self.root/'image.png';source.write_bytes(raster())
        images=[{'path':str(source),'mime':'image/png'}]
        class RPC:
            wait_time=0;tick=None
            def __init__(self):self.pending=[];self.calls=[]
            def send(self,method,params):
                self.calls.append((method,params));self.pending=[{'id':1,'result':{'stopReason':'end_turn'}}];return 1
            def request(self,method,params):
                self.calls.append((method,params));self.pending=[{'method':'turn/completed','params':{'turn':{'id':'turn','status':'completed'}}}];return {'turn':{'id':'turn'}}
        for name,capable in (('Codex',True),('DeepSeek',True),('DeepSeek',False)):
            agent=Agent(name,'sid');agent.rpc=RPC();agent.image_capable=capable
            agent.prompt('image prompt',images=images)
            method,params=agent.rpc.calls[0]
            blocks=params['input' if name=='Codex' else 'prompt']
            if name=='Codex':self.assertEqual(blocks[1],{'type':'localImage','path':str(source)})
            elif capable:self.assertEqual(base64.b64decode(blocks[1]['data']),raster())
            else:self.assertIn('未声明直接看图能力',blocks[0]['text']);self.assertEqual(len(blocks),1)


if __name__=='__main__': unittest.main()

import base64
import json
import re
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from server import Room,create_http
from test_audio import REAL_MP3
from test_room import wait_for


class FakeAudioAgent:
    calls=[]
    def __init__(self,name,sid=None):self.name=name;self.id=sid or name;self.cwd=None
    def open(self):pass
    def close(self):pass
    def prompt(self,text,images=None,**kwargs):
        self.calls.append((self.name,text,images))
        return {'status':'completed','text':'收到'}


class AudioHTTP(unittest.TestCase):
    def test_audio_upload_persists_downloads_and_is_not_sent_as_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            FakeAudioAgent.calls=[];room=Room(Path(tmp)/'room.db',FakeAudioAgent);room.auto=False
            http=create_http(room,0);threading.Thread(target=http.serve_forever,daemon=True).start()
            url='http://127.0.0.1:'+str(http.server_port)
            try:
                with urllib.request.urlopen(url) as r:
                    token=re.search(r'name="room-token" content="([^"]+)"',r.read().decode())[1]
                body=json.dumps({'text':'','audios':[{'name':'test.mp3','data':base64.b64encode(REAL_MP3).decode()}]}).encode()
                request=urllib.request.Request(url+'/api/send',data=body,headers={'Content-Type':'application/json','X-Room-Token':token})
                with urllib.request.urlopen(request) as r:self.assertEqual(r.status,200)
                wait_for(lambda:len(FakeAudioAgent.calls)==2 and room.snapshot()['active'] is None)
                item=room.snapshot()['messages'][0]['attachments'][0]
                self.assertEqual(item['kind'],'audio');self.assertEqual(item['mime'],'audio/mpeg')
                with urllib.request.urlopen(url+item['url']) as r:
                    self.assertEqual(r.headers.get_content_type(),'audio/mpeg');self.assertEqual(r.read(),REAL_MP3)
                for _,prompt,images in FakeAudioAgent.calls:
                    self.assertIsNone(images);self.assertIn('localPath',prompt)
                with urllib.request.urlopen(url+'/api/export') as r:
                    self.assertEqual(json.load(r)[0]['attachments'][0]['url'],item['url'])
            finally:http.shutdown();http.server_close();room.close()
            reopened=Room(Path(tmp)/'room.db',FakeAudioAgent)
            try:self.assertEqual(reopened.snapshot()['messages'][0]['attachments'][0]['url'],item['url'])
            finally:reopened.close()


if __name__=='__main__':unittest.main()

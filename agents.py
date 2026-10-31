"""Official stdio adapters. Public text and user-directed approval requests."""
import json, os, queue, subprocess, threading, time, uuid, shutil, base64
import hashlib
from pathlib import Path
from approvals import choices, response

ROOT = Path(__file__).resolve().parent
TURN_IDLE_SECONDS = 600
TURN_MAX_SECONDS = 7200

UNKNOWN_LOG = ROOT / 'data' / 'unknown-approvals.log'


def note_unknown(method):
    """Record a hash plus length only: enough to correlate, not to leak a name."""
    raw = str(method)
    digest = hashlib.sha256(raw.encode('utf-8', 'replace')).hexdigest()[:16]
    try:
        UNKNOWN_LOG.parent.mkdir(exist_ok=True)
        with UNKNOWN_LOG.open('a', encoding='utf-8') as handle:
            handle.write(f'sha256:{digest} len:{min(len(raw), 999)}\n')
    except OSError:
        pass


def read_access_mode():
    path=ROOT/'room-access.json'
    if not path.exists(): return 'workspace'
    mode=json.loads(path.read_text(encoding='utf-8'))['mode']
    if mode not in ('workspace','full'): raise ValueError('聊天室权限配置无效。')
    return mode

def write_access_mode(mode):
    if mode not in ('workspace','full'): raise ValueError('请选择工作区权限或全盘访问。')
    path=ROOT/'room-access.json';temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'mode':mode}),encoding='utf-8');temporary.replace(path)

def harness_access_patch():
    """Use the supported launcher overlay and canonical preset service."""
    path=ROOT/'data'/'room-access.patch.yml'
    plugin=(ROOT/'room-harness-access.mjs').as_uri()
    content=('\n- id: permission\n  config:\n    presets:\n'
        '      read-only: {sandbox: read-only, approval: ask}\n'
        '      workspace-write: {sandbox: workspace-write, approval: ask}\n'
        '      danger-full-access: {sandbox: danger-full-access, approval: never}\n'
        '      room-full-access: {sandbox: danger-full-access, approval: ask}\n'
        '- insert:\n    - id: room-session-access\n      name: '+json.dumps(plugin)+'\n')
    path.parent.mkdir(exist_ok=True)
    path.write_text(content,encoding='utf-8')
    return path


class TurnClock:
    """Activity extends the idle window; approval waits do not consume either limit."""
    def __init__(self, now):
        self.started = self.last_activity = now

    def deadline(self):
        return min(self.started + TURN_MAX_SECONDS, self.last_activity + TURN_IDLE_SECONDS)

    def touch(self, now):
        self.last_activity = now
def find_codex():
    configured = os.environ.get('ROOM_CODEX_EXE')
    if configured and Path(configured).is_file(): return configured
    found = shutil.which('codex')
    if found: return found
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'OpenAI/Codex/bin'
    candidates = list(base.glob('*/codex.exe'))
    if candidates: return str(max(candidates,key=lambda p:p.stat().st_mtime))
    raise FileNotFoundError('找不到Codex程序，请打开Codex完成更新后重试。')

def codex_environment():
    """Use existing explicit proxy, or Windows' enabled HTTP proxy; do not change it."""
    env=os.environ.copy()
    if not any(env.get(k) for k in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy')):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
                enabled=winreg.QueryValueEx(key,'ProxyEnable')[0]
                raw=winreg.QueryValueEx(key,'ProxyServer')[0]
            if enabled and raw:
                if '=' in raw:
                    parts=dict(part.split('=',1) for part in raw.split(';') if '=' in part)
                    raw=parts.get('https') or parts.get('http')
                if raw:
                    env['HTTPS_PROXY']=raw if '://' in raw else 'http://'+raw
                    env['HTTP_PROXY']=env['HTTPS_PROXY']
        except (OSError,ImportError,ValueError): pass
    bypass=env.get('NO_PROXY',env.get('no_proxy',''))
    env['NO_PROXY']=','.join(filter(None,[bypass,'localhost','127.0.0.1','::1']))
    return env
DSH = [r'D:\harness\DeepSeek Harness.exe', '--expose-internals',
       r'D:\harness\resources\app.asar\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js', '--profile', 'acp']

class RPC:
    def __init__(self, argv, env=None, request_handler=None):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.inbox=queue.Queue(); self.seq=0; self.stderr=[]; self.pending=[]; self.tick=None
        self.request_handler=request_handler; self.wait_time=0
        def read():
            for line in self.proc.stdout:
                try: self.inbox.put(json.loads(line))
                except ValueError: pass
        def errors():
            for line in self.proc.stderr:
                self.stderr.append(line.rstrip())
                self.stderr=self.stderr[-30:]
        threading.Thread(target=read,daemon=True).start()
        threading.Thread(target=errors,daemon=True).start()
    def send(self, method, params, request=True):
        self.seq+=1
        msg={'jsonrpc':'2.0','method':method,'params':params}
        if request: msg['id']=self.seq
        self.proc.stdin.write(json.dumps(msg)+'\n'); self.proc.stdin.flush()
        return self.seq
    def receive(self, deadline):
        while time.monotonic()-self.wait_time<deadline:
            if self.tick: self.tick()
            try: msg=self.inbox.get(timeout=.5)
            except queue.Empty:
                if self.proc.poll() is not None: raise RuntimeError(f'process exited: {self.proc.returncode}; '+'\n'.join(self.stderr[-3:]))
                continue
            if 'method' in msg and 'id' in msg:
                reply={'jsonrpc':'2.0','id':msg['id']}
                method=msg['method']; params=msg.get('params',{})
                if choices(method,params):
                    choice=None; started=time.monotonic()
                    try:
                        if self.request_handler: choice=self.request_handler(method,params)
                    finally: self.wait_time+=time.monotonic()-started
                    reply['result']=response(method,params,choice)
                else:
                    note_unknown(method)
                    reply['error']={'code':-32601,'message':'This client does not implement this interactive request; describe the required input to the user in your answer.'}
                self.proc.stdin.write(json.dumps(reply)+'\n'); self.proc.stdin.flush()
                continue
            return msg
        raise TimeoutError('等待Agent消息超时。')
    def request(self, method, params, timeout=45):
        rid=self.send(method,params); deadline=time.monotonic()+timeout-self.wait_time
        while True:
            try: msg=self.receive(deadline)
            except TimeoutError as exc:
                raise TimeoutError(f'{method} 请求超过 {timeout} 秒未完成，请检查连接后继续。') from exc
            if msg.get('id')==rid:
                if 'error' in msg: raise RuntimeError(json.dumps(msg['error'],ensure_ascii=False))
                return msg.get('result',{})
            self.pending.append(msg)
    def close(self):
        try: self.proc.stdin.close()
        except OSError: pass
        try: self.proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.proc.terminate(); self.proc.wait(timeout=5)

def list_codex_models():
    rpc=RPC([find_codex(),'app-server','--listen','stdio://'],codex_environment())
    try:
        rpc.request('initialize',{'clientInfo':{'name':'room_model_catalog','version':'0.2'}})
        rpc.send('initialized',{},False)
        models=[]; cursor=None
        while True:
            page=rpc.request('model/list',{'cursor':cursor} if cursor else {})
            models.extend(page.get('data',[]))
            cursor=page.get('nextCursor')
            if not cursor: return models
    finally: rpc.close()


def read_codex_power():
    """Independent account read; no thread, model request or billing mutation."""
    rpc=RPC([find_codex(),'app-server','--listen','stdio://'],codex_environment())
    try:
        rpc.request('initialize',{'clientInfo':{'name':'room_subscription_power','version':'1'}},timeout=15)
        rpc.send('initialized',{},False)
        return rpc.request('account/rateLimits/read',{},timeout=15)
    finally: rpc.close()


def harness_session_cwd(rpc, session_id):
    """The Harness resume cwd must match its persisted session, not the room install path."""
    cursor=None; seen=set()
    while True:
        page=rpc.request('session/list',{'cursor':cursor} if cursor else {})
        for session in page.get('sessions',[]):
            if session.get('sessionId')==session_id:
                cwd=session.get('cwd')
                if not isinstance(cwd,str) or not Path(cwd).is_absolute():
                    raise RuntimeError('Harness原会话未返回有效工作目录，已停止恢复，保留原会话。')
                return cwd
        cursor=page.get('nextCursor')
        if not cursor or cursor in seen: break
        seen.add(cursor)
    raise RuntimeError('Harness会话列表中未找到绑定的原会话，已停止恢复，未创建替代会话。')

def process_tree(pid):
    """Return descendant PIDs only; command lines and prompts are never read."""
    if not pid: return None
    try:
        out=subprocess.run(['powershell.exe','-NoProfile','-Command',
            'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress'],
            capture_output=True,text=True,timeout=8,creationflags=subprocess.CREATE_NO_WINDOW).stdout
        rows=json.loads(out or '[]')
        if isinstance(rows,dict): rows=[rows]
        children={}
        for row in rows:
            children.setdefault(row.get('ParentProcessId'),[]).append(row.get('ProcessId'))
    except Exception:
        return None
    found=[]; stack=[pid]
    while stack:
        for child in children.get(stack.pop(),[]):
            if child not in found: found.append(child); stack.append(child)
    return found

class Agent:
    def __init__(self, name, session=None, effort=None):
        self.name=name; self.id=session; self.rpc=None; self.active=None
        self.effort=effort; self.open_timings={}; self.model=None
        self.request_handler=None
        self.progress_handler=None
        self.rate_limit_handler=None
        self.selected_model=None
        self.cwd=None
        self.image_capable=False
        self.access_mode='workspace';self.manage_permissions=False;self.access_status=None
    def open(self):
        opening=time.monotonic()
        if self.name=='DeepSeek':
            env=os.environ.copy(); env['ELECTRON_RUN_AS_NODE']='1'
            command=list(DSH);proof=None
            if self.manage_permissions:
                command.extend(['--patch',str(harness_access_patch())])
                proof=ROOT/'data'/('access-proof-'+uuid.uuid4().hex+'.json')
                env.update(ROOM_ACCESS_SESSION=self.id or '',ROOM_ACCESS_MODE=self.access_mode,ROOM_ACCESS_PROOF=str(proof))
            self.rpc=RPC(command,env,self.request_handler)
            initialized=self.rpc.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'local-group-room','version':'0.1.0'}})
            self.image_capable=bool(initialized.get('agentCapabilities',{}).get('promptCapabilities',{}).get('image'))
            self.cwd=harness_session_cwd(self.rpc,self.id) if self.id else str(ROOT)
            result=self.rpc.request('session/resume' if self.id else 'session/new',
                {'cwd':self.cwd,'mcpServers':[],**({'sessionId':self.id} if self.id else {})})
            self.id=self.id or result['sessionId']
            if proof:
                if not proof.exists(): raise RuntimeError('Harness未确认聊天室权限已生效，已停止连接。')
                self.access_status=json.loads(proof.read_text(encoding='utf-8'));proof.unlink()
                expected='danger-full-access' if self.access_mode=='full' else 'workspace-write'
                if (self.access_status.get('sessionId')!=self.id or self.access_status.get('mode')!=self.access_mode
                    or self.access_status.get('sandbox')!=expected or self.access_status.get('approval')!='ask'):
                    raise RuntimeError('Harness权限验证与绑定会话不一致。')
            # Use the user's desktop-selected official account route if advertised.
            for option in result.get('configOptions',[]):
                if option.get('category')=='model':
                    for group in option.get('options',[]):
                        if group.get('group')=='deepseek-account':
                            match=next((v for v in group.get('options',[]) if 'deepseek-flash' in v.get('value','')),None)
                            if match:
                                self.rpc.request('session/set_config_option',{'sessionId':self.id,'configId':option['id'],'value':match['value']})
                                print('DeepSeek: selected existing official account model',flush=True)
        else:
            self.rpc=RPC([find_codex(),'app-server','--listen','stdio://'],codex_environment(),self.request_handler)
            self.rpc.request('initialize',{'clientInfo':{'name':'local_group_room','version':'0.1.0'}})
            self.open_timings['handshakeSeconds']=round(time.monotonic()-opening,3)
            self.rpc.send('initialized',{},False)
            params={'approvalPolicy':'on-request','sandbox':'danger-full-access' if self.access_mode=='full' else 'workspace-write'}
            if self.id: params['threadId']=self.id
            else: params['cwd']=str(ROOT)
            result=self.rpc.request('thread/resume' if self.id else 'thread/start',params)
            self.id=result['thread']['id']
            self.cwd=result['thread'].get('cwd') or self.cwd or str(ROOT)
            self.model=result.get('model')
            if self.manage_permissions:
                expected='dangerFullAccess' if self.access_mode=='full' else 'workspaceWrite'
                if result.get('sandbox',{}).get('type')!=expected:
                    raise RuntimeError('Codex未确认请求的权限模式，可能受到管理策略限制。')
                if result.get('approvalPolicy') not in ('on-request','onRequest'):
                    raise RuntimeError('Codex未保留请求确认策略，已停止连接。')
                self.access_status={'mode':self.access_mode,'sandbox':expected,
                    'approval':result.get('approvalPolicy'),'verified':True}
        self.open_timings['readySeconds']=round(time.monotonic()-opening,3)
        self.rpc.pending.clear()
        print(self.name+': session ready '+self.id,flush=True)
    def prompt(self,text,cancel_event=None,on_text=None,images=None):
        start=time.monotonic(); first=None; chunks=[]; status=None
        if self.name=='DeepSeek':
            blocks=[{'type':'text','text':text}]
            if self.image_capable:
                blocks.extend({'type':'image','mimeType':item['mime'],'data':base64.b64encode(Path(item['path']).read_bytes()).decode('ascii')} for item in images or [])
            elif images:
                blocks[0]['text']+='\n连接器未声明直接看图能力；请用图片工具读取附件localPath。若工具不支持，请明确告知，勿声称已看过图片。'
            rid=self.rpc.send('session/prompt',{'sessionId':self.id,'prompt':blocks})
        else:
            params={'threadId':self.id,'input':[{'type':'text','text':text}]}
            params['input'].extend({'type':'localImage','path':item['path']} for item in images or [])
            if self.selected_model: params['model']=self.selected_model
            if self.effort: params['effort']=self.effort
            result=self.rpc.request('turn/start',params)
            self.active=result['turn']['id']; rid=None
        cancelled=False
        def tick():
            nonlocal cancelled
            if cancel_event and cancel_event.is_set() and not cancelled:
                cancelled=True
                if self.name=='DeepSeek': self.rpc.send('session/cancel',{'sessionId':self.id},False)
                elif self.active: self.rpc.send('turn/interrupt',{'threadId':self.id,'turnId':self.active})
        self.rpc.tick=tick
        clock=TurnClock(time.monotonic()-self.rpc.wait_time)
        while True:
            try:
                msg=self.rpc.pending.pop(0) if self.rpc.pending else self.rpc.receive(clock.deadline())
            except TimeoutError as exc:
                self.rpc.tick=None
                elapsed=time.monotonic()-self.rpc.wait_time-clock.started
                reason='本轮已达到2小时运行上限' if elapsed>=TURN_MAX_SECONDS else '连续10分钟未收到Agent进展'
                raise TimeoutError(f'{self.name}：{reason}，已请求停止。已执行的文件修改可能保留，请检查后继续，避免重复操作。') from exc
            clock.touch(time.monotonic()-self.rpc.wait_time)
            if self.name=='DeepSeek':
                if msg.get('id')==rid:
                    if 'error' in msg: raise RuntimeError(json.dumps(msg['error'],ensure_ascii=False))
                    status=msg.get('result',{}).get('stopReason'); break
                if msg.get('method')=='session/update':
                    update=msg.get('params',{}).get('update',{})
                    if update.get('sessionUpdate')=='agent_message_chunk':
                        chunk=update.get('content',{}).get('text','')
                        if chunk:
                            chunks.append(chunk)
                            if on_text: on_text("".join(chunks))
                            if first is None: first=time.monotonic()-start
            else:
                p=msg.get('params',{})
                if msg.get('method')=='account/rateLimits/updated' and self.rate_limit_handler:
                    self.rate_limit_handler(p)
                if self.progress_handler and msg.get('method') in ('item/started','item/completed'):
                    item=p.get('item',{})
                    labels={'commandExecution':'执行命令','fileChange':'修改文件','webSearch':'搜索资料',
                            'mcpToolCall':'调用工具','dynamicToolCall':'调用工具','contextCompaction':'整理上下文'}
                    label=labels.get(item.get('type'))
                    if label: self.progress_handler(('正在' if msg['method']=='item/started' else '已完成')+label)
                if msg.get('method')=='item/agentMessage/delta':
                    chunks.append(p.get('delta',''))
                    if on_text: on_text(''.join(chunks))
                    if first is None: first=time.monotonic()-start
                if msg.get('method')=='turn/completed' and p.get('turn',{}).get('id')==self.active:
                    status=p['turn']['status']
                    if p['turn'].get('error'): raise RuntimeError(json.dumps(p['turn']['error'],ensure_ascii=False))
                    self.active=None; break
        self.rpc.tick=None
        answer=''.join(chunks)
        return {'speaker':self.name,'text':answer,'status':status,'firstTextSeconds':round(first,3) if first is not None else None,'totalSeconds':round(time.monotonic()-start,3)}
    def close(self):
        if not self.rpc: return
        self.rpc.tick=None
        try:
            if self.name=='DeepSeek': self.rpc.send('session/cancel',{'sessionId':self.id},False)
            elif self.active: self.rpc.request('turn/interrupt',{'threadId':self.id,'turnId':self.active},timeout=8)
        except Exception: pass
        self.rpc.close(); self.rpc=None

const $=id=>document.getElementById(id);let last='',initialized=false,lastActive=false,localListening=false;
let lastRequestsSignature='';
let showWork=false,workCount=0;
function renderRoomName(name){const h=$('room-name');if(!h)return;const text=name||'';h.textContent=text||'给这里取个名字吧';if(text)h.classList.remove('unset');else h.classList.add('unset');}
function applyWorkBar(){const bar=$('workbar');if(!bar)return;bar.hidden=!workCount;const button=$('toggle-work');if(button)button.textContent=(showWork?'隐藏':'显示')+'工作记录（'+workCount+'）';}
function renderRequests(items,total){const panel=$('requests-list');if(!panel)return;if(!Array.isArray(items)){panel.textContent='服务暂不支持待办';return;}const signature=JSON.stringify([items,total]);if(signature===lastRequestsSignature)return;lastRequestsSignature=signature;const pending=Number.isInteger(total)?total:items.filter(x=>x.status==='pending').length;$('requests-count').textContent=pending?`(${pending})`:'';panel.replaceChildren();if(!items.length){panel.textContent='暂无待办';return;}for(const owner of ["user","agents"]){const group=items.filter(x=>(x.owner||"user")===owner);const heading=document.createElement("h3");heading.textContent=owner==="user"?"需要你处理":"我们正在做";panel.append(heading);if(!group.length){const empty=document.createElement("div");empty.className="hint";empty.textContent="暂无事项";panel.append(empty);continue;}for(const item of group){const row=document.createElement('div');row.style.cssText='padding:8px 0;border-bottom:1px solid #d9e3e6;overflow-wrap:anywhere';const label=document.createElement('strong');label.textContent=(item.priority==='required'?'较急':'有空再看')+' · '+item.source;const body=document.createElement('div');body.textContent=item.text;const meta=document.createElement('div');meta.textContent=new Date(item.created*1000).toLocaleString('zh-CN')+' · '+({pending:'待处理',done:'已完成',cancelled:'已取消'}[item.status]||item.status);row.append(label,body,meta);for(const [status,title] of (item.status==='pending'?[['done','完成'],['cancelled','取消']]:[['pending','重新打开']])){const button=document.createElement('button');button.type='button';button.textContent=title;button.style.cssText='padding:2px 8px;margin:4px 4px 0 0';button.onclick=action(()=>call('request-status',{id:item.id,status}));row.append(button);}panel.append(row);}}}
let token=document.querySelector('meta[name="room-token"]').content;
async function call(action,data={}){const send=()=>fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Room-Token':token},body:JSON.stringify(data)});let r=await send();if(r.status===403){const page=await fetch('/',{cache:'no-store'});if(!page.ok)throw Error('无法更新页面认证，请刷新页面');const doc=new DOMParser().parseFromString(await page.text(),'text/html');const next=doc.querySelector('meta[name="room-token"]')?.content;if(!next||next===token)throw Error('请求来源校验失败，请刷新页面或检查访问地址');token=next;r=await send();}const v=await r.json();if(!r.ok)throw Error(v.error||'操作失败');await refresh();}
function message(m){const box=document.createElement('article');box.className='msg '+m.role+(m.status==='interrupted'?' partial':'')+(m.draft?' draft-preview':'')+(m.category==='work'?' work':'');const by=document.createElement('div');by.className='by';const source=m.role==='Codex'?'/avatars/codex-c2bbd076f47f.png':m.role==='DeepSeek'?'/avatars/deepseek-e0f23791bdae.png':null;const badge=document.createElement(source?'img':'span');badge.className=source?'message-avatar':'dot';if(source){badge.src=source;badge.alt='';badge.width=28;badge.height=28;badge.decoding='async';}by.append(badge);const name=document.createElement('span');name.textContent=m.role==='user'?'你':m.role==='system'?'提醒':m.role;by.append(name);const time=document.createElement('span');time.textContent=m.draft?'正在生成…':new Date(m.time*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})+(m.status==='interrupted'?' · 已中断':'');by.append(time);const bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=m.text;if(m.attachments?.length){const gallery=document.createElement('div');gallery.className='message-images';for(const item of m.attachments){if(item.kind==='audio'){if(!/^\/media\/[a-f0-9]{64}\.(mp3|wav|m4a|ogg)$/.test(item.url))continue;const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.className='message-audio';audio.src=item.url;gallery.append(audio);continue;}if(!/^\/media\/[a-f0-9]{64}\.(png|jpg|gif|webp)$/.test(item.url))continue;const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noopener';const image=document.createElement('img');image.src=item.url;image.alt=item.name||'图片';image.loading='lazy';image.decoding='async';link.append(image);gallery.append(link);}bubble.append(gallery);}box.append(by,bubble);return box;}
// Keyed reconciliation: unchanged messages (and their audio players) keep their DOM nodes.
function syncMessages(list,messages,draft){
 const wanted=[];let seq=0;for(const m of messages)wanted.push([m.id===undefined||m.id===null?'idx:'+(seq++):String(m.id),JSON.stringify(m),m]);
 if(draft)wanted.push(['__draft__',JSON.stringify(draft),draft]);
 let index=0;
 for(const [id,sig,data] of wanted){
  let el=list.querySelector('[data-id="'+id+'"]');
  if(!el||el.dataset.sig!==sig){const fresh=message(data);fresh.dataset.id=id;fresh.dataset.sig=sig;if(el)el.replaceWith(fresh);el=fresh;}
  if(list.children[index]!==el)list.insertBefore(el,list.children[index]||null);
  index++;
 }
 while(list.children.length>index)list.lastElementChild.remove();
}
function serviceErrorText(raw,state={}){
 if(!raw)return '';
 let error;try{error=JSON.parse(raw);}catch{return raw;}
 if(error?.code===-32603&&typeof error.message==='string'&&error.message.includes('DeepSeek Messages transport failed')){
  return 'DeepSeek 与模型服务的消息传输失败（-32603）。\n本轮已暂停，原会话和聊天记录保留。稍后点“继续”会重新建立连接。\n不能仅凭这条错误确定是临时网络中断还是上游服务异常。若本轮涉及文件、关机等操作，请先检查执行进度，避免重复执行。';
 }
 const code=typeof error?.codexErrorInfo==='string'?error.codexErrorInfo:error?.codexErrorInfo?.type;
 if(code!=='serverOverloaded')return raw;
 const model=state.lastCodex?.model||state.model||'当前所选模型';
 return 'GPT 模型 '+model+' 当前服务繁忙（serverOverloaded）。\n本轮已暂停，已有文字已保留。稍后点“继续”重试，或在模型下拉框换一个模型后继续。\n若本轮已执行文件操作，请先检查进度；系统不会自动换模型或重复执行任务。';
}
async function refresh(){try{const r=await fetch('/api/state');if(!r.ok)throw Error('本机服务不可用');const s=await r.json();lastActive=!!s.active;renderRoomName(s.roomName);renderRequests(s.requests,s.requestPendingTotal);renderApproval(s.approval);renderModels(s);renderAccess(s);renderPower(s.power);$('status').textContent=s.active?s.active+' · '+(s.approval?'等待你的审批':(s.activity||'正在回应'))+' · 已运行 '+s.elapsed+' 秒'+(s.publicationHeld?(s.paused?' · 已暂停发言':' · 完成后台生成后回应新消息'):(s.paused?' · 正在请求停止':'')):(s.paused?s.notice:'等待接力'+(s.waiting?' · '+s.waiting+' 秒':''));$('count').textContent=`本次回答 ${s.used} 次`+(s.limit?`（上限 ${s.limit} 次）`:'');$('resume').disabled=!!s.active||!s.paused;$('error').hidden=!s.error;$('error').textContent=serviceErrorText(s.error,s);if(!initialized){$('auto').checked=s.auto;$('interval').value=s.interval;$('limit').value=s.limit;initialized=true;}const signature=JSON.stringify([s.messages,s.draft,s.active,s.publicationHeld,localListening]);if(signature!==last){last=signature;const list=$('messages');const bottom=list.scrollHeight-list.scrollTop-list.clientHeight<90;syncMessages(list,s.messages,(s.active&&!s.publicationHeld&&!localListening)?{role:s.active,text:s.draft||'正在组织回答…',draft:true}:null);if(bottom)list.scrollTop=list.scrollHeight;workCount=s.messages.filter(m=>m.category==='work').length;applyWorkBar();}$('send').disabled=s.external;$('handoff').disabled=s.external;$('return').disabled=!s.external||s.releasing;$('resume').disabled=(!!s.active&&!s.publicationHeld)||!s.paused||s.external||s.inputBlocked||hasDraft();const targets=$('sessions');targets.replaceChildren();for(const item of s.sessions||[]){const line=document.createElement('div');line.textContent=item.name+' 会话：'+item.id;targets.append(line);if(item.name==='Codex'&&s.external&&!s.releasing){const link=document.createElement('a');link.href='codex://threads/'+encodeURIComponent(item.id);link.textContent='在Codex打开绑定会话';targets.append(link);}}if(s.external){const help=document.createElement('p');help.textContent='Harness：在原生应用的历史记录中查找此会话。工作区：'+s.workspace;targets.append(help);}}catch(e){$('status').textContent='连接已断开，请检查本机服务是否运行。';$('send').disabled=true;}}
function action(fn){return async e=>{e.preventDefault();$('toast').textContent='';try{await fn();}catch(err){$('toast').textContent=err.message;}}}
$('compose').onsubmit=action(async()=>{
 if(sending)throw Error('消息正在发送，请稍候。');
 const text=$('text').value,edited=editVersion,files=[...selectedImages],sounds=[...selectedAudios];
 if(!text.trim()&&!files.length&&!sounds.length)throw Error('请输入消息、选择图片或音频。');
 sending=true;
 try{
  await settingsQueue;
  const images=await Promise.all(files.map(async item=>({name:item.file.name,data:await encodeImage(item.file)})));
  const audios=await Promise.all(sounds.map(async item=>({name:item.file.name,data:await encodeImage(item.file)})));
  const revision=++draftRevision;
  draftQueue=draftQueue.catch(()=>{}).then(()=>call('send',{text,images,audios,...modelChoice(),clientId,revision}));
  await draftQueue;
  const sent=new Set(files.map(item=>item.id));for(const item of selectedImages)if(sent.has(item.id))URL.revokeObjectURL(item.url);
  selectedImages=selectedImages.filter(item=>!sent.has(item.id));
  const sentSounds=new Set(sounds.map(item=>item.id));for(const item of selectedAudios)if(sentSounds.has(item.id))URL.revokeObjectURL(item.url);
  selectedAudios=selectedAudios.filter(item=>!sentSounds.has(item.id));renderImagePreview();
  if(editVersion===edited)$('text').value='';
  announcedDraft=null;localListening=hasDraft();notifyDraft();
 }finally{sending=false;}
});
$('text').onkeydown=e=>{if(!e.isComposing&&e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();$('compose').requestSubmit();}};
$('pause').onclick=action(async()=>{localListening=true;await call('pause');});
$('pause-now').onclick=action(async()=>{localListening=true;await call('pause');});
$('resume').onclick=action(async()=>{await settingsQueue;await draftQueue;await call('resume',modelChoice());localListening=false;});
$('settings').onclick=action(()=>call('settings',{auto:$('auto').checked,interval:Number($('interval').value),limit:Number($('limit').value),...modelChoice()}));
$('handoff').onclick=action(()=>call('handoff'));
$('return').onclick=action(()=>call('return'));
$('room-name').onclick=()=>{const h=$('room-name');const current=h.classList.contains('unset')?'':h.textContent;const name=window.prompt('给这里取个名字（留空则恢复提示）',current);if(name===null)return;call('room-name',{name:name.trim()});};
$('toggle-work').onclick=()=>{showWork=!showWork;document.querySelector('.chat').classList.toggle('show-work',showWork);applyWorkBar();};
let lastApproval='';
function renderApproval(request){
 const signature=JSON.stringify(request);if(signature===lastApproval)return;lastApproval=signature;
 const panel=$('approval');panel.replaceChildren();panel.hidden=!request;if(!request)return;
 const title=document.createElement('strong');title.textContent=request.name+' 正在等待你的工具操作审批';
 const detail=document.createElement('pre');detail.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px';detail.textContent=JSON.stringify(request.details,null,2);
 const method=document.createElement('div');method.textContent=request.method;method.className='hint';
 panel.append(title,method,detail);
 for(const option of request.choices){const button=document.createElement('button');button.textContent=option.label;button.style.marginRight='8px';button.onclick=action(async()=>{await call('approval',{id:request.id,choice:option.id});});panel.append(button);}
}
async function poll(){await refresh();setTimeout(poll,lastActive?250:1500);}poll();

let catalog=[],catalogKey='',modelInitialized=false,settingsQueue=Promise.resolve();
const effortNames={low:'快速',medium:'深入',high:'高',xhigh:'很高',max:'最大',ultra:'极致'};
function modelChoice(){return {model:$('model').value,effort:$('effort').value};}
function fillEfforts(value){
 const selected=catalog.find(m=>m.model===$('model').value);
 const options=selected?selected.supportedReasoningEfforts.map(o=>o.reasoningEffort):['low','medium','high','xhigh','max','ultra'];
 $('effort').replaceChildren(...options.map(v=>new Option((effortNames[v]||v)+' · '+v,v)));
 $('effort').value=options.includes(value)?value:(selected?.defaultReasoningEffort||options[0]);
}
function renderModels(s){
 // Old running servers do not support these controls until restart.
 if(!Array.isArray(s.models)){$('model').disabled=true;$('effort').disabled=true;$('model-status').textContent='新版服务将在本轮结束后启用，请稍后刷新。';return;}
 const key=JSON.stringify(s.models);
 if(key!==catalogKey||!modelInitialized){
  const chosen=modelInitialized?$('model').value:s.model;
  const effort=modelInitialized?$('effort').value:s.effort;
  catalog=s.models;catalogKey=key;
  const items=[new Option('沿用会话模型',''),...catalog.map(m=>new Option(m.displayName||m.model,m.model))];
  if(chosen&&!catalog.some(m=>m.model===chosen))items.push(new Option(chosen+'（待校验）',chosen));
  $('model').replaceChildren(...items);$('model').value=chosen;fillEfforts(effort);modelInitialized=true;
 }
 $('model').disabled=!catalog.length;$('effort').disabled=!catalog.length;
 $('model-status').textContent=s.modelsError?'模型列表读取失败：'+s.modelsError:!catalog.length?'正在读取可选模型…':'已保存：'+(s.model||'沿用会话模型')+' / '+s.effort;
 const c=s.lastCodex;$('model-used').textContent=c?'最近一轮提交：'+(c.model||'会话模型')+' / '+c.effort:'';
}
function saveModelChoice(){
 const choice=modelChoice();$('model-save').textContent='正在保存…';
 settingsQueue=settingsQueue.catch(()=>{}).then(()=>call('settings',choice));
 settingsQueue.then(()=>{$('model-save').textContent='已保存，下一轮生效；正在生成的回答保持原配置。';},e=>{$('model-save').textContent='保存失败：'+e.message;$('toast').textContent=e.message;});
}
$('model').onchange=()=>{fillEfforts($('effort').value);saveModelChoice();};
$('effort').onchange=saveModelChoice;

// Only draft presence is sent; unsent text stays in this browser.
const clientId=crypto.randomUUID();
let draftRevision=0,editVersion=0,announcedDraft=null,draftQueue=Promise.resolve(),sending=false;
function notifyDraft(force=false){
 const hasText=hasDraft();
 if(!force&&hasText===announcedDraft)return draftQueue;
 announcedDraft=hasText;
 const revision=++draftRevision;
 if(hasText){localListening=true;const previews=$('messages').querySelectorAll('.draft-preview');previews.forEach(p=>p.remove());$('resume').disabled=true;$('status').textContent='你正在输入，暂停发言，后台可继续生成…';}
 draftQueue=draftQueue.catch(()=>{}).then(()=>call('typing',{clientId,revision,hasText}));
 draftQueue.catch(e=>{announcedDraft=null;$('toast').textContent='输入暂停未送达：'+e.message;});
 return draftQueue;
}
$('text').oninput=()=>{editVersion++;notifyDraft();};
$('auto').onchange=action(()=>call('settings',{auto:$('auto').checked}));
setInterval(()=>{if(!sending&&hasDraft())notifyDraft(true);},5000);
window.addEventListener('pageshow',()=>{notifyDraft();});
window.addEventListener('pagehide',()=>{
 const revision=++draftRevision;
 fetch('/api/typing',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json','X-Room-Token':token},body:JSON.stringify({clientId,revision,hasText:false})}).catch(()=>{});
 announcedDraft=null;
});

let accessInitialized=false;
function renderAccess(s){
 if(!('accessMode' in s)){$('access').disabled=true;$('access-status').textContent='权限界面待服务更新后启用。';return;}
 $('access').disabled=false;
 if(!accessInitialized){$('access').value=s.accessMode;accessInitialized=true;}
 const verified=Object.entries(s.accessStatus||{}).filter(([name,status])=>status?.verified&&status.mode===s.accessMode).map(([name])=>name);
 $('access-status').textContent='已设置：'+(s.accessMode==='full'?'全盘访问，保留确认':'工作区访问')+'；'+(verified.length?'已确认：'+verified.join('、'):'等待下一轮连接确认。');
}
$('access').onchange=action(async()=>{await call('access',{mode:$('access').value});});

// Selected images remain browser-local until the explicit send action.
let selectedImages=[];let selectedAudios=[];
function hasDraft(){return $('text').value.length>0||selectedImages.length>0||selectedAudios.length>0;}
function encodeImage(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('图片读取失败，请重新选择。'));reader.readAsDataURL(file);});}
function renderImagePreview(){
 const panel=$('image-preview');panel.replaceChildren();
 for(const item of selectedImages){const chip=document.createElement('div');chip.className='image-chip';const image=document.createElement('img');image.src=item.url;image.alt=item.file.name;
 const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.title='移除图片';remove.setAttribute('aria-label','移除 '+item.file.name);
 remove.onclick=()=>{selectedImages=selectedImages.filter(v=>v.id!==item.id);URL.revokeObjectURL(item.url);renderImagePreview();notifyDraft();};
 const label=document.createElement('small');label.textContent=item.file.name;chip.append(image,remove,label);panel.append(chip);}
 for(const item of selectedAudios){const chip=document.createElement('div');chip.className='image-chip';const mark=document.createElement('div');mark.textContent='🎵';mark.style.fontSize='28px';mark.style.lineHeight='1';
 const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.title='移除音频';remove.setAttribute('aria-label','移除 '+item.file.name);
 remove.onclick=()=>{selectedAudios=selectedAudios.filter(v=>v.id!==item.id);URL.revokeObjectURL(item.url);renderImagePreview();notifyDraft();};
 const label=document.createElement('small');label.textContent=item.file.name;chip.append(mark,remove,label);panel.append(chip);}
}
const AUDIO_TYPES=['audio/mpeg','audio/wav','audio/mp4','audio/ogg','audio/x-m4a','audio/mp3'];
function addAudio(files){
 const incoming=Array.from(files);if(!incoming.length)return;
 try{
  if(selectedAudios.length+incoming.length>2)throw Error('每条消息最多2个音频。');
  if(incoming.some(f=>!AUDIO_TYPES.includes(f.type)&&!/\.(mp3|wav|m4a|ogg)$/i.test(f.name)))throw Error('请选择 MP3、WAV、M4A 或 OGG 音频。');
  if(incoming.some(f=>!f.size||f.size>10*1024*1024))throw Error('每个音频不能超过10 MB。');
  if([...selectedAudios.map(v=>v.file),...incoming].reduce((n,f)=>n+f.size,0)>20*1024*1024)throw Error('音频合计不能超过20 MB。');
  selectedAudios.push(...incoming.map(file=>({id:crypto.randomUUID(),file,url:URL.createObjectURL(file)})));renderImagePreview();notifyDraft();$('toast').textContent='';
 }catch(error){$('toast').textContent=error.message;}
}
function addFiles(files){const list=Array.from(files);if(!list.length)return;const sounds=list.filter(f=>f.type.startsWith('audio/')||/\.(mp3|wav|m4a|ogg)$/i.test(f.name));const pictures=list.filter(f=>!sounds.includes(f));if(pictures.length)addImages(pictures);if(sounds.length)addAudio(sounds);}
function addImages(files){
 const incoming=Array.from(files);if(!incoming.length)return;
 try{
  if(selectedImages.length+incoming.length>4)throw Error('每条消息最多4张图片。');
  if(incoming.some(f=>!['image/png','image/jpeg','image/gif','image/webp'].includes(f.type)))throw Error('请选择 PNG、JPEG、GIF 或 WebP 图片。');
  if(incoming.some(f=>!f.size||f.size>8*1024*1024))throw Error('每张图片不能超过8 MB。');
  if([...selectedImages.map(v=>v.file),...incoming].reduce((n,f)=>n+f.size,0)>20*1024*1024)throw Error('图片合计不能超过20 MB。');
  selectedImages.push(...incoming.map(file=>({id:crypto.randomUUID(),file,url:URL.createObjectURL(file)})));renderImagePreview();notifyDraft();$('toast').textContent='';
 }catch(error){$('toast').textContent=error.message;}
}
$('pick-image').onclick=()=>{$('image-files').click();};
$('image-files').onchange=()=>{addFiles($('image-files').files);$('image-files').value='';};
$('text').onpaste=e=>{const files=Array.from(e.clipboardData?.items||[]).filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter(Boolean).filter(file=>file.type.startsWith('image/')||file.type.startsWith('audio/'));if(files.length){e.preventDefault();addFiles(files);}};
$('compose').ondragover=e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files')){e.preventDefault();$('compose').classList.add('dragover');}};
$('compose').ondragleave=()=>{$('compose').classList.remove('dragover');};
$('compose').ondrop=e=>{if(!e.dataTransfer?.files?.length)return;e.preventDefault();$('compose').classList.remove('dragover');addFiles(e.dataTransfer.files);};
$('pick-emoji').onclick=()=>{const panel=$('emoji-panel');panel.hidden=!panel.hidden;$('pick-emoji').setAttribute('aria-expanded',String(!panel.hidden));};
for(const emoji of ['😀','😄','😂','🥹','😊','🤔','😎','😭','😮','😴','🤗','🙌','👍','👏','🙏','❤️','✨','🎉','👀','🐱','🌱','☕','🚀','💡']){
 const button=document.createElement('button');button.type='button';button.textContent=emoji;button.setAttribute('aria-label',emoji);
 button.onclick=()=>{const text=$('text'),start=text.selectionStart??text.value.length,end=text.selectionEnd??start;if(text.value.length-(end-start)+emoji.length>12000)return;text.setRangeText(emoji,start,end,'end');editVersion++;notifyDraft();text.focus();};$('emoji-panel').append(button);
}

// Display service-reported subscription windows; never simulate charging at reset.
let lastPower='';
function renderPower(power){
 const status=$('power-status'),panel=$('power-windows');
 $('power-refresh').disabled=!!power?.loading;
 if(!power){status.textContent='电量显示待服务更新后启用。';panel.replaceChildren();return;}
 const signature=JSON.stringify(power);if(signature===lastPower)return;lastPower=signature;
 const labels={normal:'电量充足',low:'低电量 · 请伙伴分担',critical:'电量很低 · 优先交接',empty:'电量不足 · 等待恢复',unknown:'电量未知'};
 status.textContent=(power.status==='unknown'?(power.loading?'正在读取电量…':power.error||'暂时读不到电量'):power.status==='stale'?'显示上次读数 · 待更新':labels[power.level]||'电量未知')+(power.blocked?' · 服务端暂时限制使用':'');
 panel.replaceChildren();
 for(const bucket of power.buckets||[]){
  for(const window of bucket.windows||[]){
   const remaining=window.remainingPercent,level=remaining===0?'empty':remaining<=5?'critical':remaining<=20?'low':'normal';
   const row=document.createElement('div');row.className='power-window '+level+(window.stale?' stale':'');
   const label=document.createElement('label'),name=document.createElement('span'),value=document.createElement('strong');
   name.textContent=(power.buckets.length>1?bucket.name+' · ':'')+window.label;value.textContent=(window.stale?'上次 ':'')+remaining+'%';label.append(name,value);
   const meter=document.createElement('meter');meter.min=0;meter.max=100;meter.low=20;meter.high=50;meter.optimum=100;meter.value=remaining;meter.setAttribute('aria-label',name.textContent+'剩余'+remaining+'%'+(window.stale?'，上次读数':''));
   const reset=document.createElement('div');reset.className='power-reset';reset.textContent=window.resetsAt?(window.stale?'原恢复时间：':'恢复时间：')+new Date(window.resetsAt*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'恢复时间待服务端提供';
   row.append(label,meter,reset);panel.append(row);
  }
 }
 const updated=power.updatedAt?new Date(power.updatedAt*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):'';
 $('power-help').textContent='订阅余量，非电脑电池。'+(updated?'读取于 '+updated+'。':'')+'低于或等于20%时提醒双方分担；不换算为剩余回答次数。';
}
$('power-refresh').onclick=action(()=>call('power'));

// Exercise browser event ordering without contacting either model.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
function browser(){
 const elements=new Map(),events={},requests=[];let uid=0;
 const state={messages:[],draft:'',active:null,paused:true,auto:true,interval:15,limit:40,used:0,
  accessMode:'workspace',accessStatus:{},publicationHeld:false,error:'',notice:'paused',external:false,sessions:[],models:[],model:'',effort:'low',inputBlocked:false};
 const element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',checked:false,style:{},dataset:{},children:[],hidden:true,classList:{add(){},remove(){}},setAttribute(name,value){this[name]=value;},focus(){},click(){},setRangeText(text,start,end){this.value=this.value.slice(0,start)+text+this.value.slice(end);},
   querySelector(sel){const m=String(sel).match(/^\[data-id="(.+)"\]$/);if(!m)return null;return this.children.find(c=>c.dataset&&c.dataset.id===m[1])||null;},
   insertBefore(node,ref){const i=ref?this.children.indexOf(ref):-1;this.children.splice(i<0?this.children.length:i,0,node);return node;},
   get lastElementChild(){return this.children[this.children.length-1]||null;},
   replaceWith(node){for(const p of elements.values()){const i=p.children.indexOf(this);if(i>=0){p.children[i]=node;return;}}},
   querySelectorAll(){return this.children.filter(c=>c.className?.includes('draft-preview'));},remove(){for(const p of elements.values())p.children=p.children.filter(c=>c!==this);},scrollHeight:0,scrollTop:0,clientHeight:0,append(...items){this.children.push(...items);},
   replaceChildren(...items){this.children=items;},requestSubmit(){return this.onsubmit({preventDefault(){}});}});
  return elements.get(id);
 };
 let holdSend=false,releaseSend,failSend=false;
 const context=vm.createContext({
  document:{getElementById:element,querySelector:()=>({content:'test-token'}),createElement:()=>element(Symbol())},
  crypto:{randomUUID:()=> 'browser-'+(++uid)},URL:{createObjectURL:()=> 'blob:local-'+(++uid),revokeObjectURL(){}},
  FileReader:class{readAsDataURL(file){this.result='data:'+file.type+';base64,aW1hZ2U=';this.onload();}},
  Option:class{constructor(text,value){this.textContent=text;this.value=value;}},
  window:{addEventListener:(name,fn)=>{events[name]=fn;}},
  setTimeout(){},setInterval(){},
  fetch:async(url,options)=>{
   if(!options)return {ok:true,json:async()=>JSON.parse(JSON.stringify(state))};
   const body=JSON.parse(options.body);requests.push({url,body});
   if(url==='/api/send'&&failSend)return {ok:false,json:async()=>({error:'upload rejected'})};
   if(url==='/api/send'&&holdSend)await new Promise(resolve=>{releaseSend=resolve;});
   if(url==='/api/typing'){state.inputBlocked=body.hasText;if(body.hasText){state.paused=true;state.publicationHeld=!!state.active;}}
   if(url==='/api/send'){state.inputBlocked=false;state.paused=false;}
   if(url==='/api/pause'){state.paused=true;state.publicationHeld=!!state.active;}
   if(url==='/api/settings'&&'auto' in body)state.auto=body.auto;
   if(url==='/api/access')state.accessMode=body.mode;
   return {ok:true,json:async()=>({ok:true})};
  }
 });
 vm.runInContext(fs.readFileSync('dist/app.js','utf8'),context);
 return {element,events,requests,state,renderPower:power=>{context.powerFixture=power;vm.runInContext('renderPower(powerFixture)',context);},hold(){holdSend=true;},release(){releaseSend();},fail(){failSend=true;}};
}
async function test(){
 const b=browser();await settle();assert.equal(b.element('auto').checked,true);
 b.element('text').value='尚未发送的私人草稿';b.element('text').oninput();await settle();
 let typing=b.requests.filter(r=>r.url==='/api/typing').at(-1);
 assert.equal(typing.body.hasText,true);assert.equal('text' in typing.body,false);
 assert.equal(JSON.stringify(typing).includes('私人草稿'),false);
 assert.equal(b.element('resume').disabled,true);
 b.element('text').value='';b.element('text').oninput();await settle();
 assert.equal(b.state.paused,true);assert.equal(b.state.inputBlocked,false);
 b.element('text').value=' ';b.element('text').oninput();await settle();
 assert.equal(b.state.inputBlocked,true); // Whitespace is still draft content.
 b.element('text').value='GPT新的问题';b.element('text').oninput();
 await b.element('compose').requestSubmit();await settle();
 assert.equal(b.element('text').value,'');
 const send=b.requests.find(r=>r.url==='/api/send');
 assert.equal(send.body.text,'GPT新的问题');assert.ok(send.body.revision>typing.body.revision);
 await b.element('pause-now').onclick({preventDefault(){}});
 await b.element('pause').onclick({preventDefault(){}});
 assert.equal(b.requests.filter(r=>r.url==='/api/pause').length,2);
 b.element('auto').checked=false;await b.element('auto').onchange({preventDefault(){}});
 assert.equal(b.state.auto,false);
 // New typing while sending must survive the send response and re-pause the room.
 b.element('text').value='GPT提交这条';b.element('text').oninput();await settle();
 b.hold();const sending=b.element('compose').requestSubmit();await settle();
 b.element('text').value='发送过程中继续写';b.element('text').oninput();
 b.release();await sending;await settle();
 assert.equal(b.element('text').value,'发送过程中继续写');assert.equal(b.state.inputBlocked,true);
 assert.equal(b.state.paused,true);
 await b.events.pagehide();await settle();
 assert.equal(b.requests.at(-1).body.hasText,false);
 const c=browser();c.state.active='Codex';c.state.draft='unpublished preview';await settle();
 assert.equal(c.element('messages').querySelectorAll('.draft-preview').length,1);
 c.element('text').value='我想先说';c.element('text').oninput();
 assert.equal(c.element('messages').querySelectorAll('.draft-preview').length,0);
 await settle();assert.equal(c.element('messages').querySelectorAll('.draft-preview').length,0);
 c.element('text').value='';c.element('text').oninput();await settle();
 assert.equal(c.element('resume').disabled,false); // Background completion does not block explicit resume.
 b.element('access').value='full';await b.element('access').onchange({preventDefault(){}});assert.equal(b.state.accessMode,'full');
 const avatarBrowser=browser();avatarBrowser.state.messages=[{role:'Codex',text:'test',time:1},{role:'DeepSeek',text:'test',time:1},{role:'user',text:'test',time:1}];await settle();
 const badges=avatarBrowser.element('messages').children.map(m=>m.children[0].children[0]);
 assert.ok(badges[0].src.startsWith('/avatars/codex-'));assert.ok(badges[1].src.startsWith('/avatars/deepseek-'));assert.equal(badges[2].className,'dot');
 const images=browser();await settle();
 const file={name:'表情.gif',size:20,type:'image/gif'};
 images.element('image-files').files=[file];images.element('image-files').onchange();await settle();
 assert.equal(images.element('image-preview').children.length,1);
 assert.equal(images.requests.filter(r=>r.url==='/api/send').length,0);
 assert.equal(images.requests.at(-1).body.hasText,true);assert.equal('images' in images.requests.at(-1).body,false);
 await images.element('compose').requestSubmit();await settle();
 const imageSend=images.requests.find(r=>r.url==='/api/send');assert.equal(imageSend.body.text,'');assert.equal(imageSend.body.images[0].name,'表情.gif');
 assert.equal(images.element('image-preview').children.length,0);
 images.element('text').onpaste({clipboardData:{items:[{kind:'file',type:'image/gif',getAsFile:()=>file}]},preventDefault(){}});await settle();
 assert.equal(images.element('image-preview').children.length,1);
 images.element('image-preview').children[0].children[1].onclick();await settle();assert.equal(images.state.inputBlocked,false);assert.equal(images.state.paused,true);
 images.element('compose').ondrop({dataTransfer:{files:[file]},preventDefault(){}});await settle();assert.equal(images.element('image-preview').children.length,1);
 images.element('emoji-panel').children[0].onclick();assert.equal(images.element('text').value,'😀');
 // Reject oversize images and active formats without sending any file contents.
 images.element('image-files').files=[{name:'bad.svg',size:20,type:'image/svg+xml'}];images.element('image-files').onchange();assert.ok(images.element('toast').textContent.includes('PNG'));
 images.element('image-files').files=[{name:'big.png',size:9*1024*1024,type:'image/png'}];images.element('image-files').onchange();assert.ok(images.element('toast').textContent.includes('8 MB'));
 const gallery=browser();gallery.state.messages=[{role:'user',text:'x',time:1,attachments:[{name:'emoji',url:'/media/'+'a'.repeat(64)+'.gif'},{name:'unsafe',url:'javascript:alert(1)'}]}];await settle();
 const rendered=gallery.element('messages').children[0].children[1].children[0];assert.equal(rendered.children.length,1);assert.equal(rendered.children[0].children[0].src,'/media/'+'a'.repeat(64)+'.gif');
 const failure=browser();await settle();failure.element('image-files').files=[file];failure.element('image-files').onchange();failure.fail();await failure.element('compose').requestSubmit();await settle();assert.equal(failure.element('image-preview').children.length,1);assert.equal(failure.element('toast').textContent,'upload rejected');
 const concurrent=browser();await settle();concurrent.element('image-files').files=[file];concurrent.element('image-files').onchange();concurrent.hold();const photoSend=concurrent.element('compose').requestSubmit();await settle();concurrent.element('image-files').files=[{...file,name:'新的表情.gif'}];concurrent.element('image-files').onchange();concurrent.release();await photoSend;await settle();assert.equal(concurrent.element('image-preview').children.length,1);assert.equal(concurrent.element('image-preview').children[0].children[2].textContent,'新的表情.gif');assert.equal(concurrent.state.inputBlocked,true);assert.equal(concurrent.state.paused,true);
 const power=browser();await settle();
 const battery={status:'ok',level:'low',updatedAt:1000,loading:false,blocked:false,buckets:[{name:'Codex',windows:[{label:'5小时电量',remainingPercent:7,resetsAt:2000,stale:false},{label:'7天电量',remainingPercent:26,resetsAt:10000,stale:false}]}]};
 power.renderPower(battery);assert.ok(power.element('power-status').textContent.includes('低电量'));
 assert.equal(power.element('power-windows').children[0].children[1].value,7);
 power.renderPower({...battery,status:'stale',level:'unknown',buckets:[{...battery.buckets[0],windows:[{...battery.buckets[0].windows[0],stale:true}]}]});
 assert.ok(power.element('power-status').textContent.includes('上次读数'));assert.ok(power.element('power-windows').children[0].children[0].children[1].textContent.includes('上次 7%'));
 power.renderPower({status:'unknown',buckets:[],level:'unknown',error:'无法读取'});assert.equal(power.element('power-windows').children.length,0);assert.equal(power.element('power-status').textContent,'无法读取');
 await power.element('power-refresh').onclick({preventDefault(){}});assert.equal(power.requests.at(-1).url,'/api/power');
 const audioBrowser=browser();const audioItem={name:'voice.mp3',size:1024,type:'audio/mpeg'};
 audioBrowser.state.messages=[{id:1,role:'Codex',text:'听听',time:1,attachments:[{kind:'audio',name:'voice.mp3',url:'/media/'+'b'.repeat(64)+'.mp3'}]}];await settle();
 const audioNode=audioBrowser.element('messages').children[0];
 const audioEl=audioNode.children[1].children[0].children[0];
 assert.equal(audioEl.src,'/media/'+'b'.repeat(64)+'.mp3');assert.equal(audioEl.preload,'none');assert.equal(audioEl.controls,true);
 // A streaming draft elsewhere must not rebuild existing players.
 // Any later refresh must keep existing message nodes and players, not rebuild them.
 audioBrowser.state.draft='正在想';audioBrowser.element('auto').checked=false;await audioBrowser.element('auto').onchange({preventDefault(){}});await settle();
 assert.equal(audioBrowser.element('messages').children[0],audioNode);
 assert.equal(audioBrowser.element('messages').children[0].children[1].children[0].children[0],audioEl);
 assert.equal(audioBrowser.element('messages').children.length,1);
 audioBrowser.element('text').onpaste({clipboardData:{items:[{kind:'file',type:'audio/mpeg',getAsFile:()=>audioItem}]},preventDefault(){}});await settle();
 assert.equal(audioBrowser.element('image-preview').children.length,1);
 assert.equal(audioBrowser.requests.at(-1).body.hasText,true);
 audioBrowser.element('image-files').files=[{name:'huge.mp3',size:11*1024*1024,type:'audio/mpeg'}];audioBrowser.element('image-files').onchange();
 assert.ok(audioBrowser.element('toast').textContent.includes('10 MB'));
 const overloaded=browser();
 overloaded.state.model='gpt-6.1-terra';
 overloaded.state.lastCodex={model:'gpt-6.1-terra',effort:'high'};
 overloaded.state.error=JSON.stringify({message:'Selected model is at capacity. Please try a different model.',codexErrorInfo:'serverOverloaded'});
 await settle();
 assert.equal(overloaded.element('error').hidden,false);
 assert.ok(overloaded.element('error').textContent.includes('gpt-6.1-terra 当前服务繁忙'));
 assert.ok(overloaded.element('error').textContent.includes('继续'));
 assert.equal(overloaded.state.model,'gpt-6.1-terra');
 assert.equal(overloaded.requests.some(r=>r.url==='/api/send'||r.url==='/api/resume'),false);
 const transportFailure=browser();
 transportFailure.state.error=JSON.stringify({code:-32603,message:'Internal error: turn failed: DeepSeek Messages transport failed'});
 await settle();
 assert.ok(transportFailure.element('error').textContent.includes('DeepSeek 与模型服务的消息传输失败'));
 assert.ok(transportFailure.element('error').textContent.includes('重新建立连接'));
 assert.equal(transportFailure.requests.some(r=>r.url==='/api/send'||r.url==='/api/resume'),false);
 const otherInternalFailure=browser();
 otherInternalFailure.state.error=JSON.stringify({code:-32603,message:'unrelated internal failure'});
 await settle();
 assert.equal(otherInternalFailure.element('error').textContent,otherInternalFailure.state.error);
 const otherError=browser();otherError.state.error='another failure';await settle();
 assert.equal(otherError.element('error').textContent,'another failure');
 console.log('Browser event checks passed, including capacity errors without automatic model switches or retries, media drafts, emoji, audio playback continuity, real/stale/unknown power display and manual refresh.');
}
test().catch(error=>{console.error(error);process.exitCode=1;});

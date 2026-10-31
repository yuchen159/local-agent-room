import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {apply} from './room-harness-access.mjs';
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'room-access-test-'));
try{
 for(const mode of ['full','workspace']){
  const proof=path.join(folder,mode+'.json'),calls=[],handlers={};
  process.env.ROOM_ACCESS_SESSION='bound-session';process.env.ROOM_ACCESS_MODE=mode;process.env.ROOM_ACCESS_PROOF=proof;
  let current='';
  const ctx={sessions:{list:()=>[{id:'other-session'},{id:'bound-session'}]},
   on:(name,fn)=>{handlers[name]=fn;},permissionPresets:{
    set:(session,preset)=>{calls.push([session.id,preset]);current=preset;},current:()=>current,
    resolve:preset=>({sandbox:preset==='room-full-access'?'danger-full-access':'workspace-write',approval:'ask'})}};
  apply(ctx);
  assert.equal(calls.length,1);assert.equal(calls[0][0],'bound-session');
  handlers['session/created']({id:'another-session'});assert.equal(calls.length,1);
  const result=JSON.parse(fs.readFileSync(proof,'utf8'));
  assert.equal(result.sessionId,'bound-session');assert.equal(result.approval,'ask');assert.equal(result.mode,mode);
 }
 console.log('Harness adapter tests passed: bound-session scope, full/workspace modes, confirmation policy, actual-mode proof.');
}finally{if(path.dirname(path.resolve(folder))!==path.resolve(os.tmpdir())||!path.basename(folder).startsWith('room-access-test-'))throw Error('Unexpected cleanup path');fs.rmSync(folder,{recursive:true});}

// Scoped to the one session restored by this room's dedicated ACP process.
import fs from 'node:fs';
export const name='room-session-access';
export const inject=['permissionPresets','sessions'];
export function apply(ctx){
 const target=process.env.ROOM_ACCESS_SESSION;
 const mode=process.env.ROOM_ACCESS_MODE;
 const proof=process.env.ROOM_ACCESS_PROOF;
 if(!['workspace','full'].includes(mode)||target===undefined||!proof)
  throw Error('Room permission adapter requires an explicit mode and session scope.');
 const preset=mode==='full'?'room-full-access':'workspace-write';
 const update=session=>{
  if(target&&String(session.id)!==target)return;
  ctx.permissionPresets.set(session,preset);
  const current=ctx.permissionPresets.current(session);
  if(current!==preset)throw Error('Harness did not apply the requested room preset.');
  const spec=ctx.permissionPresets.resolve(current);
  fs.writeFileSync(proof,JSON.stringify({sessionId:String(session.id),mode,preset:current,
   sandbox:spec.sandbox,approval:spec.approval,verified:true}),'utf8');
 };
 ctx.on('session/created',update);
 for(const session of ctx.sessions.list())update(session);
}

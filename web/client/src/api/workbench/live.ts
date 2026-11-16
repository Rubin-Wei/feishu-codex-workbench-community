import {api} from './index';
import type {LiveReply,LiveSnapshot} from '@shared/workbench';

/** The hosting gateway only supports HTTP. Read small versioned updates sequentially. */
export function followLive(onUpdate:(value:LiveSnapshot)=>void):()=>void {
 let stopped=false,revision=0,failures=0;
 let timer:ReturnType<typeof setTimeout>|undefined;
 async function poll(){
  let delay=1500;
  try{
   if(!document.hidden){
    const r=await api<LiveReply>('/api/live?after='+revision);
    if(stopped)return;
    if(r.changed&&r.value&&r.revision>revision){revision=r.revision;onUpdate(r.value)}
    delay=450;failures=0;
   }
  }catch{failures++;delay=Math.min(10000,1000*failures)}
  if(!stopped)timer=setTimeout(poll,delay);
 }
 void poll();return()=>{stopped=true;clearTimeout(timer)};
}

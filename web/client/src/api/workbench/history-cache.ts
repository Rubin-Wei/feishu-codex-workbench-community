import {api,command} from './index';
import type {CachedHistory,History,Snapshot,Thread} from '@shared/workbench';

const values=new Map<string,{value:History;checked:number}>();
const requests=new Map<string,Promise<History|null>>();
const cacheKey=(host:string,thread:string):string=>host+':'+thread;
export function peekHistory(host:string,thread:string):History|undefined{return values.get(cacheKey(host,thread))?.value}
export function storeHistory(host:string,thread:string,value:History):void {
  const key=cacheKey(host,thread);values.delete(key);values.set(key,{value,checked:Date.now()});
  if(values.size>180)values.delete(values.keys().next().value!);
}
export function clearHistoryCache():void{values.clear();requests.clear()}
export async function readHistory(host:string,thread:string,force=false,cacheOnly=false):Promise<History|null>{
  const key=cacheKey(host,thread),cached=values.get(key);
  if(!force&&cached&&Date.now()-cached.checked<30000)return cached.value;
  if(!force&&requests.has(key))return requests.get(key)!;
  const request=(async()=>{
    if(!force){
      const hit=await api<CachedHistory>('/api/history?host='+encodeURIComponent(host)+'&thread='+encodeURIComponent(thread));
      if(hit.cached&&hit.value){storeHistory(host,thread,hit.value);return hit.value}
      if(cacheOnly)return null;
    }
    const value=await command('history',{host,thread});storeHistory(host,thread,value);return value;
  })();
  requests.set(key,request);
  try{return await request}finally{if(requests.get(key)===request)requests.delete(key)}
}

export function prefetchHistories(snapshot:Snapshot,selectedHost:string):()=>void {
  let cancelled=false;
  const catalogs=Object.entries(snapshot.catalogs||{});
  const candidates:{host:string;thread:Thread}[]=[];
  // Warm recent chats across every cluster, then every chat in the selected machine.
  for(let i=0;i<3;i++)for(const [host,c] of catalogs){const thread=c.threads?.[i];if(thread)candidates.push({host,thread})}
  for(const thread of snapshot.catalogs?.[selectedHost]?.threads||[])candidates.push({host:selectedHost,thread});
  const seen=new Set<string>();
  const pending=candidates.filter(({host,thread})=>{const key=cacheKey(host,thread.id);if(seen.has(key))return false;seen.add(key);return true});
  async function worker(){
    while(pending.length&&!cancelled){
      const item=pending.shift()!;
      try{await readHistory(item.host,item.thread.id,false,true)}catch{/* On-demand reads display a retryable error. */}
    }
  }
  for(let i=0;i<3;i++)void worker();
  return()=>{cancelled=true};
}

import axios from 'axios';
import {axiosForBackend} from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';
import type {CommandPoll,CommandReplies,Snapshot} from '@shared/workbench';
export function errorMessage(error:unknown):string {
 if(axios.isAxiosError(error))return error.response?.data?.error?.message || '网络请求失败，请稍后重试';
 return error instanceof Error ? error.message : '操作失败';
}
export async function api<T=Snapshot>(url:string,options?:{method?:string;data?:unknown}):Promise<T>{
 try {const r=await axiosForBackend<T>({url,method:options?.method||'GET',data:options?.data,
   meta:{autoJumpToLogin:false},headers:{'Cache-Control':'no-store'}});return r.data;}
 catch(e:unknown){if(axios.isAxiosError(e)&&e.response?.status===401)window.dispatchEvent(new Event('workbench-login-required'));throw e;}
}
export async function command<K extends keyof CommandReplies>(action:K,args:object):Promise<CommandReplies[K]>{
 const id=crypto.randomUUID();
 await api('/api/commands',{method:'POST',data:{id,action,args}});
 for(let i=0;i<95;i++){
  await new Promise(r=>setTimeout(r,1000));
  const r=await api<CommandPoll<CommandReplies[K]>>('/api/commands?id='+id);
  if(r.status==='done')return r.result;
  if(['failed','unknown'].includes(r.status))throw Error(r.result?.error||'操作未完成');
 }
 throw Error('暂未收到服务器确认。没有重发操作；请刷新任务状态。');
}
export async function login(username:string,password:string):Promise<void>{
 await axiosForBackend({url:'/api/login',method:'POST',data:{username,password},meta:{autoJumpToLogin:false}});
}
export async function logout():Promise<void>{await api('/api/logout',{method:'POST'});window.dispatchEvent(new Event('workbench-login-required'));}

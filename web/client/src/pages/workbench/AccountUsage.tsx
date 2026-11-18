import {useEffect,useRef,useState} from 'react';
import {RefreshCw,UserRound} from 'lucide-react';
import {command,errorMessage} from '@client/src/api/workbench';
import type {AccountUsage as Usage} from '@shared/workbench';

export function resetLabel(resetsAt:number|null,now=Date.now()):string {
 if(!resetsAt)return '重置时间暂不可用';
 const minutes=Math.max(0,Math.ceil((resetsAt*1000-now)/60000));
 if(!minutes)return '等待额度更新';
 const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60);
 return days?`${days} 天${hours?` ${hours} 小时`:''}后重置`:hours?`${hours} 小时后重置`:`${minutes} 分钟后重置`;
}

export function AccountUsage({host,online}:{host:string;online:boolean}){
 const [usage,setUsage]=useState<Usage|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const refresh=useRef<(force?:boolean)=>void>(()=>{});
 useEffect(()=>{
  let disposed=false,busy=false;
  setUsage(null);setError('');setLoading(false);
  async function load(force=false){
   if(busy||!online)return;busy=true;setLoading(true);
   try{const result=await command('account',{host,force});if(!disposed){setUsage(result);setError('')}}
   catch(e){if(!disposed)setError(errorMessage(e))}
   finally{busy=false;if(!disposed)setLoading(false)}
  }
  refresh.current=load;void load();
  const timer=setInterval(()=>{if(!document.hidden)void load()},60000);
  return()=>{disposed=true;clearInterval(timer)};
 },[host,online]);
 const account=usage?.account;
 const identity=account?.email||(account?.type==='apiKey'?'API Key 账户':usage?.status==='not_logged_in'?'Codex 未登录':account?'Codex 账户':'Codex 账户信息');
 const unavailable=error||usage?.error||(!online?'等待后台连接':loading?'正在读取…':'周限额暂不可用');
 return <section className="account-usage" aria-label="当前机器的 Codex 账户和额度">
  <div className="account-identity"><UserRound size={14}/><span title={identity}>{identity}</span>{account?.planType&&<small>{account.planType}</small>}</div>
  {usage?.weekly?<div className="weekly-usage"><span>每周剩余 <b>{Math.round(usage.weekly.remainingPercent)}%</b></span><progress max="100" value={usage.weekly.remainingPercent} aria-label="每周剩余额度"/><span title={usage.weekly.resetsAt?new Date(usage.weekly.resetsAt*1000).toLocaleString():undefined}>{resetLabel(usage.weekly.resetsAt)}</span></div>:<span className="usage-note" title={unavailable}>{usage?.status==='api_key'?'API Key 用量请查看计费平台':unavailable}</span>}
  {(usage?.stale||error&&usage?.weekly)&&<span className="usage-note" title={usage?.updatedAt?new Date(usage.updatedAt).toLocaleString():undefined}>上次数据 · 更新失败</span>}
  <button className="icon" aria-label="刷新账户和额度" disabled={loading||!online} onClick={()=>refresh.current(true)}><RefreshCw size={13} className={loading?'spin':''}/></button>
 </section>;
}

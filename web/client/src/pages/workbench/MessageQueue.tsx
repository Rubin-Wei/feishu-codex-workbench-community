import {Button} from '@client/src/components/ui/button';
import type {QueuedMessage} from '@shared/workbench';
import {Clock3,X,Play,CornerUpRight} from 'lucide-react';

interface QueueProps {items:QueuedMessage[];canSteer:boolean;steerUnavailable?:string;onCancel:(id:string)=>void;onResume:(id:string)=>void;onSteer:(id:string)=>void}
const labels:Record<string,string>={accepting:'正在保存',queued:'排队中',dispatching:'正在发送',unknown:'发送待核查',failed:'未能发送'};
export function MessageQueue({items,canSteer,steerUnavailable,onCancel,onResume,onSteer}:QueueProps){
 const pending=items.filter(m=>['accepting','queued','dispatching','unknown','failed'].includes(m.status));
 if(!pending.length)return null;
 const paused=pending.find(m=>m.paused);
 return <section className="message-queue" aria-label="待发送消息">
  <div className="queue-heading"><span><Clock3 size={13}/>待发送 · {pending.length}</span>{paused&&<Button variant="ghost" size="sm" onClick={()=>onResume(paused.id)}><Play size={12}/>继续队列</Button>}</div>
  {paused&&<p className="queue-notice">{paused.paused}</p>}
  {!canSteer&&steerUnavailable&&<p className="queue-notice">{steerUnavailable}</p>}
  <div className="queue-list">{pending.map(m=><div className="queued-message" key={m.id}>
   <div><small>{m.paused&&m.status==='queued'?'已暂停':labels[m.status]}{m.mode==='steer'?' · 引导':''}</small><p>{m.prompt}</p>{m.error&&<span className="queue-error">{m.error}</span>}</div>
   <div className="queued-actions">{m.status==='queued'&&<Button variant="outline" size="sm" className="queue-steer" disabled={!canSteer} aria-label={`立即引导：${m.prompt}`} title={canSteer?'作为引导发送到当前轮次':steerUnavailable} onClick={()=>onSteer(m.id)}><CornerUpRight size={14}/>立即引导</Button>}
   {['queued','failed'].includes(m.status)&&<Button variant="ghost" size="icon" aria-label={`取消排队：${m.prompt}`} onClick={()=>onCancel(m.id)}><X size={14}/></Button>}</div>
  </div>)}</div>
 </section>;
}

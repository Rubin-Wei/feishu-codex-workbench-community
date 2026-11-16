import {useEffect,useRef,useState} from 'react';
import {peekHistory,readHistory,storeHistory,prefetchHistories,clearHistoryCache} from '@client/src/api/workbench/history-cache';
import {ModelPicker} from './ModelPicker';
import {MessageQueue} from './MessageQueue';
import {Button} from '@client/src/components/ui/button';
import {followLive} from '@client/src/api/workbench/live';
import {MessageBody} from './MessageBody';
import {groupProjects, projectName} from './projects';
import {Skeleton} from '@client/src/components/ui/skeleton';
import {api, command, errorMessage, logout} from '@client/src/api/workbench';
import type {Thread,Message,Snapshot,QuestionData,CommandReplies,QueuedMessage} from '@shared/workbench';
import {Menu,Plus,Search,ArrowUp,ChevronLeft,ChevronDown,Folder,RefreshCw,X,Square,PanelLeftClose,MessagesSquare,Command,ExternalLink} from 'lucide-react';
const statusNames:Record<string,string>={starting:'提交中',running:'进行中',waiting:'等待你的回复',unknown:'待核查',completed:'已完成',failed:'失败',interrupted:'已停止'};
export default function Workbench(){
 const [state,setState]=useState<Snapshot>({online:false,hosts:[],jobs:[],approvals:[]}),[host,setHost]=useState('supervisor'),[threads,setThreads]=useState<Thread[]>([]),[thread,setThread]=useState<Thread|null>(null),[messages,setMessages]=useState<Message[]>([]),[next,setNext]=useState<string|null>(null),[older,setOlder]=useState<string|null>(null),[query,setQuery]=useState(''),[input,setInput]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(''),[sending,setSending]=useState(false),[sidebar,setSidebar]=useState(false),[modal,setModal]=useState(false),[cwd,setCwd]=useState(''),[title,setTitle]=useState(''),[dirs,setDirs]=useState<string[]>([]),[showJobs,setShowJobs]=useState(false),[indexing,setIndexing]=useState(false),[collapsed,setCollapsed]=useState<Set<string>>(new Set()),[model,setModel]=useState('inherit'),[effort,setEffort]=useState('inherit');
 const [pendingMessages,setPendingMessages]=useState<QueuedMessage[]>([]);
 const messagesView=useRef<HTMLDivElement>(null),stickBottom=useRef(true),pendingSends=useRef(0);
 const snapshot=useRef(state),optimistic=useRef(new Map<string,{host:string;thread:Thread}>());snapshot.current=state;
 const restored=useRef(false),listGeneration=useRef(0),generation=useRef(0),tail=useRef<HTMLDivElement>(null),current=useRef({host,thread}),lastTerminal=useRef(''); current.current={host,thread};
 function catalogThreads(data:Snapshot,id:string):Thread[]{
  const remote=data.catalogs?.[id]?.threads||[];
  for(const t of remote)optimistic.current.delete(id+':'+t.id);
  return [...[...optimistic.current.values()].filter(x=>x.host===id).map(x=>x.thread),...remote];
 }
 async function refresh(){
  try{
   let data=await api('/api/state');
   if((snapshot.current.revision||0)>(data.revision||0)){const {jobs,approvals,queue,revision}=snapshot.current;data={...data,jobs,approvals,queue,revision}}
   snapshot.current=data;setState(data);
   const selected=current.current;
   if(data.catalogs?.[selected.host]){
    const list=catalogThreads(data,selected.host);setThreads(list);setIndexing(!data.catalogs[selected.host].threads);setNext(null);
    const renamed=list.find(t=>t.id===selected.thread?.id);
    if(renamed)setThread(t=>t?.id===renamed.id?{...t,...renamed}:t);
   }
   if(!restored.current){
    restored.current=true;
    try{
     const saved=JSON.parse(localStorage.getItem('codex-workbench-position')||'null');
     if(saved&&(saved.host==='supervisor'||data.hosts.some(h=>h.id===saved.host))){
      const pending=selectHost(saved.host),selection=generation.current;
      void pending.then(()=>{
       if(saved.thread&&saved.host!=='supervisor'&&selection===generation.current)
        void selectThread(data.catalogs?.[saved.host]?.threads?.find(t=>t.id===saved.thread)||{id:saved.thread,cwd:''},saved.host);
      });
     }
    }catch{/* Browser position storage is optional. */}
   }
  }catch(e:unknown){setError(errorMessage(e))}
 }
 useEffect(()=>{refresh();const t=setInterval(()=>{if(!document.hidden)refresh()},3000);return()=>{clearInterval(t);listGeneration.current++}},[]);
 useEffect(()=>followLive(value=>{if(value.revision>(snapshot.current.revision||0)){const next={...snapshot.current,...value};snapshot.current=next;setState(next)}}),[]);
 useEffect(()=>{setPendingMessages(old=>old.filter(p=>!(state.queue||[]).some(q=>q.id===p.id)))},[state.queue]);
 const catalogVersion=Object.values(state.catalogs||{}).map(c=>c.updatedAt||0).join(':');
 useEffect(()=>prefetchHistories(snapshot.current,host),[host,catalogVersion]);
 async function readSessions(id:string,cursor:string|null,reset=false){
  const g=++listGeneration.current;setIndexing(true);
  if(reset)setThreads([]);
  const cursors=new Set<string>();
  try{
   do{
    const r=await command('sessions',{host:id,cursor,limit:100});
    if(g!==listGeneration.current)return;
    setThreads(items=>[...items,...r.data.filter(t=>!items.some(existing=>existing.id===t.id))]);
    cursor=r.nextCursor;setNext(cursor);
    if(cursor&&cursors.has(cursor))throw Error('会话分页没有前进，请稍后刷新');
    if(cursor)cursors.add(cursor);
   }while(cursor&&g===listGeneration.current);
  }catch(e:unknown){if(g===listGeneration.current)setError(errorMessage(e))}
  finally{if(g===listGeneration.current)setIndexing(false)}
 }
 function remember(hostId:string,threadId?:string){try{localStorage.setItem('codex-workbench-position',JSON.stringify({host:hostId,thread:threadId}))}catch{/* Some embedded browsers disable local storage. */}}
 async function selectHost(id:string){
  remember(id);
  const g=++generation.current;++listGeneration.current;setIndexing(false);
  setInput('');setQuery('');setModal(false);setHost(id);setThread(null);setMessages([]);
  setThreads([]);setNext(null);setOlder(null);setError('');setLoading('');
  if(id!=='supervisor'){
   const catalog=snapshot.current.catalogs?.[id];
   if(catalog){setThreads(catalogThreads(snapshot.current,id));setIndexing(!catalog.threads);return}
   await readSessions(id,null,true);return;
  }
  setLoading('正在读取会话…');
  try{const r=await command('supervisor',{});if(g!==generation.current)return;
   if(r.thread){setThread(r.thread);setMessages(r.messages||[]);setOlder(r.nextCursor)}
  }catch(e:unknown){if(g===generation.current)setError(errorMessage(e))}
  finally{if(g===generation.current)setLoading('')}
 }
 async function selectThread(t:Thread,h=host,force=false){
  remember(h,t.id);stickBottom.current=true;const g=++generation.current;
  if(h!==current.current.host){setThreads(catalogThreads(snapshot.current,h));setNext(null);setQuery('');++listGeneration.current;setIndexing(false)}
  setInput('');setHost(h);setThread(t);setSidebar(false);setError('');
  const cached=peekHistory(h,t.id);
  setMessages(cached?.messages||[]);setOlder(cached?.nextCursor||null);setLoading(cached?'':'正在载入历史对话…');
  if(cached)setTimeout(()=>tail.current?.scrollIntoView(),0);
  try{
   let r=await readHistory(h,t.id,force);
   // If a cache-only prefetch was already in flight and missed, fetch once on demand.
   if(!r)r=await readHistory(h,t.id,true);
   if(!r||g!==generation.current)return;
   setMessages(r.messages);setOlder(r.nextCursor);
   const canonical=snapshot.current.catalogs?.[h]?.threads?.find(x=>x.id===t.id);
   setThread(r.thread?{...r.thread,...canonical}:t);
   setTimeout(()=>tail.current?.scrollIntoView(),80);
  }catch(e:unknown){if(g===generation.current)setError(errorMessage(e))}
  finally{if(g===generation.current)setLoading('')}
 }
 async function loadOlder(){if(!thread||!older)return;stickBottom.current=false;const g=generation.current;setLoading('正在读取更早消息…');try{const r=await command('history',{host,thread:thread.id,cursor:older});if(g!==generation.current)return;setMessages(m=>{const ids=new Set(m.map(x=>x.id));return [...r.messages.filter((x:Message)=>!ids.has(x.id)),...m]});setOlder(r.nextCursor)}catch(e:unknown){if(g===generation.current)setError(errorMessage(e))}finally{if(g===generation.current)setLoading('')}}
 const preferenceKey='codex-model:'+host+':'+(host==='supervisor'?'coordinator':thread?.id||'new');
 useEffect(()=>{try{const saved=JSON.parse(localStorage.getItem(preferenceKey)||'null');setModel(saved?.model||'inherit');setEffort(saved?.effort||'inherit')}catch{setModel('inherit');setEffort('inherit')}},[preferenceKey]);
 function chooseModel(nextModel:string,nextEffort:string){setModel(nextModel);setEffort(nextEffort);try{localStorage.setItem(preferenceKey,JSON.stringify({model:nextModel,effort:nextEffort}))}catch{/* Preferences stay in this tab when browser storage is disabled. */}}
 const jobs=state.jobs.filter(j=>j.host===host&&(!thread||j.thread===thread.id));
 const active=jobs.find(j=>['starting','running','waiting','unknown'].includes(j.status));
 useEffect(()=>{const j=state.jobs.find(j=>j.host===current.current.host&&j.thread===current.current.thread?.id&&['completed','failed','interrupted'].includes(j.status));if(j&&lastTerminal.current!==j.id){lastTerminal.current=j.id;const g=generation.current;readHistory(j.host,j.thread,true).then(r=>{if(r&&g===generation.current){setMessages(r.messages);setOlder(r.nextCursor)}}).catch(()=>{})}},[state.jobs]);
 const messageQueue=[...(state.queue||[]),...pendingMessages.filter(p=>!(state.queue||[]).some(q=>q.id===p.id))].filter(m=>m.host===host&&(!thread||m.thread===thread.id));
 const completedLive=!active?jobs.find(j=>['completed','failed','interrupted'].includes(j.status)):undefined;
 const canSteer=!!active?.turn&&['running','waiting'].includes(active.status);
 const steerUnavailable=active?.status==='unknown'?'当前任务状态待核查，核查确认后可引导。':active?'正在确认当前轮次，确认后可立即引导。':'当前没有可引导的运行任务，消息将按顺序开始。';
 useEffect(()=>{if(stickBottom.current&&messagesView.current){const box=messagesView.current;requestAnimationFrame(()=>{box.scrollTop=box.scrollHeight})}},[active?.partial,active?.partialItems,messages.length,messageQueue.length]);
 async function send(mode:'queue'|'steer'='queue'){
  if(!input.trim()||pendingSends.current>=5||(!thread&&host!=='supervisor')||(mode==='steer'&&!canSteer))return;
  setError('');const text=input,g=generation.current,id='pending:'+crypto.randomUUID();
  const queued:QueuedMessage={id,host,thread:thread?.id||'',prompt:text,mode,status:'accepting'};
  setInput('');stickBottom.current=true;pendingSends.current++;setSending(true);setPendingMessages(items=>[...items,queued]);
  try{
   const r=mode==='steer'?await command('steer',{job:active!.id,expectedTurn:active!.turn,prompt:text}):await command('enqueue',{host,thread:thread?.id,prompt:text,...(model!=='inherit'?{model}:{}),...(effort!=='inherit'?{effort}:{})});
   setPendingMessages(items=>items.map(p=>p.id===id?r:p));
   if(g===generation.current&&!thread)setThread({id:r.thread,cwd:'',name:'总管家'});
   await refresh();
  }catch(e:unknown){setPendingMessages(items=>items.filter(p=>p.id!==id));if(g===generation.current){setError(errorMessage(e));setInput(value=>value||text)}}
  finally{pendingSends.current--;setSending(pendingSends.current>0)}
 }
 async function steerQueued(id:string){if(!canSteer)return;await perform('steer',{job:active!.id,expectedTurn:active!.turn,queued:id})}

 async function perform(action:keyof CommandReplies,args:object){setError('');try{await command(action,args);await refresh()}catch(e:unknown){setError(errorMessage(e))}}
 async function browse(path:string){const g=generation.current;setCwd(path);setLoading('正在读取目录…');try{const r=await command('directories',{host,path});if(g!==generation.current)return;setCwd(r.path);setDirs(r.directories)}catch(e:unknown){if(g===generation.current)setError(errorMessage(e))}finally{if(g===generation.current)setLoading('')}}
 async function create(){if(!title.trim()||!cwd)return;const g=generation.current;setLoading('正在创建会话…');try{const r=await command('new_session',{host,cwd,title});if(g!==generation.current)return;setModal(false);optimistic.current.set(host+':'+r.id,{host,thread:r});storeHistory(host,r.id,{thread:r,messages:[]});setThreads(t=>[r,...t]);await selectThread(r)}catch(e:unknown){if(g===generation.current)setError(errorMessage(e))}finally{if(g===generation.current)setLoading('')}}
 const selectedHost=state.hosts.find(h=>h.id===host);const projects=groupProjects(threads,query);
 function openNew(path=thread?.cwd||selectedHost?.default_cwd||''){setTitle('');setDirs([]);setCwd(path);setModal(true)}
 function toggleProject(path:string){setCollapsed(previous=>{const value=new Set(previous);if(value.has(path))value.delete(path);else value.add(path);return value})}
 return <main className="app-shell">
  {sidebar&&<div className="scrim" onClick={()=>setSidebar(false)}/>}
  <aside className={'sidebar '+(sidebar?'open':'')}>
   <div className="brand"><span className="brand-icon"><Command size={18}/></span><b>Codex <span>Workspace</span></b><button className="icon mobile" aria-label="关闭菜单" onClick={()=>setSidebar(false)}><X size={18}/></button></div>
   <button className={'supervisor '+(host==='supervisor'?'selected':'')} onClick={()=>selectHost('supervisor')}><span className="spark">✳</span><span>总管家<small>{state.supervisor_model||'原生 Codex'} · {state.supervisor_effort||'默认'}</small></span><span className="keycap">⌘</span></button>
   <div className="section-label">开发机器</div>
   <div className="host-picker"><select aria-label="选择集群和机器" value={host==='supervisor'?'':host} onChange={e=>selectHost(e.target.value)}><option value="" disabled>选择集群 / 机器</option>{state.hosts.map(h=><option key={h.id} value={h.id}>{h.label}{state.catalogs?.[h.id]?.connected?' · 已连接':state.catalogs?.[h.id]?.syncing?' · 连接中':' · 重连中'}</option>)}</select><ChevronDown size={15}/></div>
   <button className="new-chat" disabled={host==='supervisor'||!state.online} onClick={()=>openNew()}><Plus size={17}/>新建会话</button>
   <div className="search"><Search size={14}/><input aria-label="搜索项目或会话" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索项目或会话"/></div>
   <div className="section-label">{host==='supervisor'?'协调会话':`项目 · ${projects.length}`} <button className="icon" aria-label="刷新会话" onClick={()=>host==='supervisor'?selectHost(host):readSessions(host,null,false)} disabled={!state.online}><RefreshCw size={13}/></button></div>
   <nav className="threads" aria-label="项目与会话">
    {host==='supervisor'?<button className="thread selected" onClick={()=>selectHost('supervisor')}><MessagesSquare size={15}/><div>我的总管家<small>跨集群安排工作</small></div></button>:
     projects.map(project=>{
      const expanded=!!query.trim()||!collapsed.has(project.path);
      return <section className="project" key={project.path}>
       <div className="project-row">
        <button className="project-toggle" aria-expanded={expanded} title={project.path} onClick={()=>toggleProject(project.path)}>
         <ChevronDown size={13} className={expanded?'':'collapsed'}/><Folder size={16}/>
         <span><b>{project.name}</b><small>{project.path}</small></span><em>{project.total}</em>
        </button>
        <button className="icon project-new" aria-label={`在 ${project.path} 新建会话`} title="在此项目新建会话" disabled={!state.online} onClick={()=>openNew(project.path)}><Plus size={15}/></button>
       </div>
       {expanded&&<div className="project-threads">{project.threads.map(t=><button className={'thread '+(thread?.id===t.id?'selected':'')} aria-current={thread?.id===t.id?'page':undefined} title={`${t.name||t.preview||'未命名会话'} · ${t.id}`} key={t.id} onClick={()=>selectThread(t)}>
        <MessagesSquare size={14}/><div>{t.name||t.preview||'未命名会话'}</div>{t.status?.type==='active'&&<i className="live-dot"/>}
       </button>)}</div>}
      </section>;
     })}
    {host!=='supervisor'&&indexing&&<div className="project-loading" aria-label="正在读取项目"><Skeleton className="h-5 w-3/4"/>{Array.from({length:5},(_,i)=><Skeleton className="h-7 w-full" key={i}/>)}</div>}
    {host!=='supervisor'&&!projects.length&&!indexing&&<div className="aside-empty">{query?'没有匹配的项目或会话':'这台机器还没有会话，可以在指定目录新建。'}</div>}
    {next&&!indexing&&<button className="more" onClick={()=>readSessions(host,next)}>继续读取项目与会话</button>}
   </nav>
   <footer className="side-footer"><span className={'status-dot '+(state.online?'online':'')}/><span>{state.online?'后台已连接':'等待后台连接'}<small>{state.controller||'Controller · 常驻服务'}</small></span><button className="icon" title="任务看板" aria-label="任务看板" onClick={()=>{setShowJobs(true);setSidebar(false)}}><PanelLeftClose size={17}/></button></footer>
  </aside>
  <section className="conversation">
   <header className="conversation-header"><button className="icon mobile" aria-label="选择会话" onClick={()=>setSidebar(true)}><Menu size={21}/></button><div><div className="breadcrumb">{host==='supervisor'?'个人工作台':`${selectedHost?.label||host} / ${thread?.cwd?projectName(thread.cwd):'项目'}`}</div><h1>{host==='supervisor'?'总管家':thread?.name||thread?.preview?.slice(0,70)||'选择一个会话'}</h1></div><div className="header-actions"><span className="model-label">{host==='supervisor'?(state.supervisor_model||'原生 Codex'):'远端 Codex'}</span><button className="icon" aria-label="刷新历史" disabled={!thread||!!loading} onClick={()=>thread&&selectThread(thread,host,true)}><RefreshCw size={16}/></button><button className="soft-button" onClick={()=>setShowJobs(true)}>任务</button><button className="icon" aria-label="退出登录" title="退出登录" onClick={async()=>{clearHistoryCache();await logout()}}><ExternalLink size={15}/></button></div></header>
   {thread?.cwd&&<div className="cwd-line"><Folder size={13}/><span>{thread.cwd}</span><code title={thread.id}>{thread.id.slice(-8)}</code></div>}
   {host!=='supervisor'&&state.catalogs?.[host]?.error&&<div className="connection-notice">该机器正在重连，先显示已同步的会话。</div>}
   {error&&<div className="error" role="alert"><span>{error}</span><button className="icon" aria-label="关闭提示" onClick={()=>setError('')}><X size={15}/></button></div>}
   <div className="messages" ref={messagesView} onScroll={()=>{const box=messagesView.current;if(box)stickBottom.current=box.scrollHeight-box.scrollTop-box.clientHeight<100}}>
    {older&&<button className="load-older" disabled={!!loading} onClick={loadOlder}>查看更早的对话</button>}
    {loading&&<div className="history-loading" aria-label={loading}>{Array.from({length:3},(_,i)=><div key={i}><Skeleton className="h-3 w-16"/><Skeleton className="h-4 w-full"/><Skeleton className="h-4 w-4/5"/></div>)}</div>}
    {!messages.length&&!loading&&<div className="welcome"><div className="welcome-mark">✳</div><h2>{host==='supervisor'?'今天，想推进哪项工作？':thread?'从这里继续工作':'你的会话，都在这里'}</h2><p>{host==='supervisor'?'告诉总管家目标，让它在合适的机器上安排、跟进和汇总。':'展开左侧项目，选择会话后自动载入历史。项目旁的 + 可在同一目录新建会话。'}</p>{host==='supervisor'&&<div className="suggestions">{['看看各个集群最近在做什么','在指定目录新建会话，检查实验进度'].map(x=><button key={x} onClick={()=>setInput(x)}>{x}<ArrowUp size={14}/></button>)}</div>}</div>}
    {messages.filter(m=>m.role!=='assistant'||!active?.partialItems?.some(p=>p.id===m.id)).map((m,i)=><article key={m.id||i} className={'message '+(m.role==='user'?'user':'assistant')}><div className="message-label">{m.role==='user'?'你':'Codex'}</div><div className="message-content"><MessageBody text={m.text}/></div></article>)}
    {messageQueue.filter(m=>m.status==='sent'&&m.message_id&&!messages.some(old=>old.id===m.message_id||old.clientId===m.message_id)).map(m=><article className="message user" key={m.id}><div className="message-label">你{m.mode==='steer'?' · 引导':''}</div><div className="message-content"><MessageBody text={m.prompt}/></div></article>)}
    {active&&<article className="message assistant"><div className="message-label"><span className="pulse-dot"/>{statusNames[active.status]||active.status}</div>{active.partialItems?.length?active.partialItems.map(p=><MessageBody key={p.id} text={p.text}/>):active.partial?<MessageBody text={active.partial}/>:<p className="muted">任务已交给 {active.host}，等待结果…</p>}<div className="task-controls"><code>{active.id}</code>{active.status==='unknown'?<button onClick={()=>perform('reconcile',{job:active.id})}>核查状态</button>:<button onClick={()=>perform('stop',{job:active.id})}><Square size={11}/>停止本轮</button>}</div></article>}
    {completedLive?.partialItems?.filter(p=>!messages.some(m=>m.id===p.id)).map(p=><article className="message assistant" key={'finished:'+p.id}><div className="message-label">Codex</div><MessageBody text={p.text}/></article>)}
    {state.approvals.filter(a=>a.host===host&&a.thread===thread?.id).map(a=><div className="approval" key={a.token}><b>需要你的操作</b><p>{a.reason}</p>{a.command&&<pre>{a.command}</pre>}{a.questions?.map((q:QuestionData)=><Question key={q.id} q={q} onAnswer={answer=>perform('answer',{token:a.token,question:q.id,answer})}/>)}{!a.questions&&<div className="approval-actions"><button onClick={()=>perform('approval',{token:a.token,accept:false})}>拒绝</button><button className="primary" onClick={()=>perform('approval',{token:a.token,accept:true})}>允许本次</button></div>}</div>)}
    <div ref={tail}/>
   </div>
   <div className="composer-wrap"><MessageQueue items={messageQueue} canSteer={canSteer} steerUnavailable={steerUnavailable} onCancel={id=>perform('cancel_queue',{id})} onResume={id=>perform('resume_queue',{id})} onSteer={steerQueued}/><ModelPicker models={state.models?.[host]||[]} model={model} effort={effort} currentModel={host==='supervisor'?state.supervisor_model:thread?.model} currentEffort={host==='supervisor'?state.supervisor_effort:thread?.reasoningEffort} disabled={sending} onChange={chooseModel}/><div className="composer"><textarea aria-label="任务内容" placeholder={host==='supervisor'?'告诉总管家你想做什么…':thread?'继续这个会话，或提交新任务…':'先从左侧选择会话…'} value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();send()}}}/><div className="composer-bottom"><span>{host==='supervisor'?'自动协调 · 按需运行':selectedHost?.label||'尚未选择机器'}</span><div className="send-actions">{active&&<Button variant="outline" size="sm" className="steer-button" title={canSteer?'补充当前正在执行的任务':steerUnavailable} disabled={!canSteer||!state.online||!input.trim()} onClick={()=>send('steer')}>引导</Button>}<button className="send" title={active?'加入队列，等当前轮次结束':'发送任务'} aria-label={active?'加入队列':'发送任务'} onClick={()=>send()} disabled={!state.online||!input.trim()||pendingSends.current>=5||(!thread&&host!=='supervisor')}><ArrowUp size={20}/></button></div></div></div><div className="composer-note">{active?'直接发送会排队；点「引导」补充当前任务。':'⌘ / Ctrl + Enter 发送 · 历史来自服务器上的原始会话'}</div></div>
  </section>
  {modal&&<div className="modal-backdrop"><section className="modal"><div className="modal-head"><h2>新建会话 <small>{selectedHost?.label}</small></h2><button className="icon" aria-label="关闭" onClick={()=>setModal(false)}><X size={20}/></button></div><label>会话名称<input value={title} onChange={e=>setTitle(e.target.value)} placeholder="例如：Qwen 训练实验"/></label><label>工作目录<div className="input-row"><input value={cwd} onChange={e=>setCwd(e.target.value)} placeholder="服务器上的绝对路径"/><button onClick={()=>browse(cwd)}>浏览</button></div></label><div className="root-links">{selectedHost?.roots.map(p=><button key={p} onClick={()=>browse(p)}>{p.split('/').pop()}</button>)}</div>{dirs.length>0&&<div className="directory-list"><button onClick={()=>browse(cwd.slice(0,cwd.lastIndexOf('/'))||'/')}><ChevronLeft size={14}/>上一级</button>{dirs.map(p=><button key={p} onClick={()=>browse(p)}><Folder size={14}/>{p.split('/').pop()}</button>)}</div>}<p className="muted">使用服务器已有的 Codex 配置和登录。</p><button className="primary create" onClick={create} disabled={!!loading||!title.trim()||!cwd}>{loading||'创建并进入'}</button></section></div>}
  {showJobs&&<div className="modal-backdrop"><section className="modal jobs-modal"><div className="modal-head"><h2>任务记录</h2><button className="icon" aria-label="关闭任务" onClick={()=>setShowJobs(false)}><X size={20}/></button></div>{!state.jobs.length&&<p className="muted">还没有提交任务。</p>}{state.jobs.map(j=><div className="job-row" key={j.id}><div><b>{j.host}</b><span className={'badge '+j.status}>{statusNames[j.status]||j.status}</span></div><p>{j.prompt}</p><small>{j.id}</small><div className="job-buttons"><button onClick={()=>{setShowJobs(false);selectThread({id:j.thread,cwd:'',name:'任务会话'},j.host)}}>打开会话</button>{j.status==='unknown'&&<button onClick={()=>perform('reconcile',{job:j.id})}>核查</button>}</div></div>)}</section></div>}
 </main>
}
function Question({q,onAnswer}:{q:QuestionData,onAnswer:(a:string)=>void}){const[a,setA]=useState('');return <div className="question"><p>{q.question}</p>{q.options?.map((o:{label:string})=><button key={o.label} onClick={()=>onAnswer(o.label)}>{o.label}</button>)}<div className="input-row"><input aria-label={q.question} value={a} onChange={e=>setA(e.target.value)} placeholder="输入补充信息"/><button disabled={!a.trim()} onClick={()=>onAnswer(a)}>回复</button></div></div>}

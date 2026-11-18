import {createContext,useCallback,useEffect,useRef,useState,type ReactNode} from 'react';
import {Download,LoaderCircle} from 'lucide-react';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from '@client/src/components/ui/dialog';
import {command,errorMessage} from '@client/src/api/workbench';
import type {FilePreviewData} from '@shared/workbench';
import type {FileTarget} from './file-links';

export const FilePreviewContext=createContext<(target:FileTarget)=>void>(()=>{});

function PreviewContents({file,line}:{file:FilePreviewData;line?:number}){
 const [url,setUrl]=useState('');
 const selectedLine=useRef<HTMLSpanElement>(null);
 useEffect(()=>{
  if(file.kind==='text')return;
  const binary=atob(file.data||''),bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));
  const objectUrl=URL.createObjectURL(new Blob([bytes],{type:file.mime}));setUrl(objectUrl);
  return()=>URL.revokeObjectURL(objectUrl);
 },[file]);
 useEffect(()=>{selectedLine.current?.scrollIntoView({block:'center'})},[file,line]);
 return <>
  <div className="preview-meta"><span>{(file.size/1024).toFixed(1)} KB · {file.mime}</span>{url&&<a href={url} download={file.name}><Download size={14}/>下载文件</a>}</div>
  {file.truncated&&<p className="preview-notice">文件较大，当前显示前 {(file.bytesRead/1024).toFixed(0)} KB。{line&&line>(file.endLine||0)?`第 ${line} 行超出预览范围。`:''}</p>}
  {file.kind==='text'?<pre className="file-text" tabIndex={0} aria-label="文件内容">{(file.text||'').split('\n').map((text,index)=>{
   const number=index+(file.startLine||1);return <span key={number} ref={number===line?selectedLine:undefined} className={'file-line '+(number===line?'selected':'')}><span className="line-number" aria-hidden="true">{number}</span><span>{text||'\n'}</span></span>;
  })}</pre>:file.kind==='image'?<div className="file-image">{url&&<img src={url} alt={file.name}/>}</div>:<div className="file-pdf">{url&&<><p>手机端若未显示 PDF，可<a href={url} target="_blank" rel="noreferrer">打开 PDF</a>或下载查看。</p><object data={url} type="application/pdf" aria-label={file.name}><a href={url} download={file.name}>下载 PDF 查看</a></object></>}</div>}
 </>;
}

export function FilePreviewProvider({host,thread,children}:{host:string;thread?:string;children:ReactNode}){
 const [target,setTarget]=useState<FileTarget|null>(null),[file,setFile]=useState<FilePreviewData|null>(null),[error,setError]=useState('');
 const generation=useRef(0),opener=useRef<HTMLElement|null>(null);
 useEffect(()=>{generation.current++;setTarget(null);setFile(null);setError('')},[host,thread]);
 const open=useCallback(async(next:FileTarget)=>{
  opener.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
  const current=++generation.current;setTarget(next);setFile(null);setError('');
  if(!thread){setError('请先打开文件所属的会话');return}
  try{const result=await command('file_preview',{host,thread,path:next.path});if(current===generation.current)setFile(result)}
  catch(e){if(current===generation.current)setError(errorMessage(e))}
 },[host,thread]);
 return <FilePreviewContext.Provider value={open}>{children}<Dialog open={!!target} onOpenChange={value=>{if(!value){generation.current++;setTarget(null);setFile(null)}}}>
  <DialogContent className="file-preview-dialog" onCloseAutoFocus={event=>{event.preventDefault();opener.current?.focus()}}>
   <DialogTitle>{file?.name||'文件预览'}</DialogTitle><DialogDescription className="preview-path">{file?.path||target?.path}{target?.line?` · 第 ${target.line} 行`:''}</DialogDescription>
   {error?<p className="preview-error" role="alert">{error}</p>:file?<PreviewContents file={file} line={target?.line}/>:<div className="preview-loading" role="status"><LoaderCircle size={20} className="spin"/>正在从会话所在机器读取文件…</div>}
  </DialogContent>
 </Dialog></FilePreviewContext.Provider>;
}

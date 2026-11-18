import {memo, useContext, useRef, useState, type ReactNode} from 'react';
import {defaultUrlTransform} from 'react-markdown';
import {FilePreviewContext} from './FilePreview';
import {fileTarget} from './file-links';
import {Check, Copy} from 'lucide-react';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import remarkMath from 'remark-math';
import {Markdown} from '@client/src/components/ui/markdown';
import {Image} from '@client/src/components/ui/image';
import 'katex/dist/katex.min.css';

function CodeBlock({children}: {children?: ReactNode}) {
  const block = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(block.current?.textContent || '');
      setCopied(true); setCopyError(false);
      setTimeout(() => setCopied(false), 2000);
    } catch { setCopyError(true); }
  }
  return <div className="code-block">
    <div className="code-toolbar"><span>{copyError ? '请长按代码选择并复制' : '代码'}</span>
      <button onClick={copy} aria-label="复制代码">{copied ? <Check size={13}/> : <Copy size={13}/>}
        {copied ? '已复制' : '复制'}</button></div>
    <pre ref={block}>{children}</pre>
  </div>;
}

export const MessageBody = memo(function MessageBody({text}: {text: string}) {
  const openFile=useContext(FilePreviewContext);
  return <Markdown className="message-markdown" remarkPlugins={[remarkMath]}
    urlTransform={url=>fileTarget(url)?url:defaultUrlTransform(url)}
    rehypePlugins={[[rehypeHighlight, {detect: false, ignoreMissing: true}], rehypeKatex]}
    components={{
      a: ({href,children}) => {
        const target=href?fileTarget(href):null;
        return target?<button className="file-link" title={`预览 ${target.path}`} onClick={()=>openFile(target)}>{children}</button>:<a href={href} target="_blank" rel="noreferrer">{children}</a>;
      },
      pre: ({children}) => <CodeBlock>{children}</CodeBlock>,
      table: ({children}) => <div className="markdown-table" tabIndex={0} role="region" aria-label="可横向滚动的表格"><table>{children}</table></div>,
      img: ({src, alt}) => {
        const target=typeof src==='string'?fileTarget(src):null;
        return target?<button className="file-link" onClick={()=>openFile(target)}>查看图片：{alt||target.path.split('/').pop()}</button>:<Image src={src} alt={alt || '会话图片'} sizes="(max-width: 760px) 90vw, 780px"/>;
      },
    }}>{text}</Markdown>;
});

import {memo, useRef, useState, type ReactNode} from 'react';
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
  return <Markdown className="message-markdown" remarkPlugins={[remarkMath]}
    rehypePlugins={[[rehypeHighlight, {detect: false, ignoreMissing: true}], rehypeKatex]}
    components={{
      pre: ({children}) => <CodeBlock>{children}</CodeBlock>,
      table: ({children}) => <div className="markdown-table" tabIndex={0} role="region" aria-label="可横向滚动的表格"><table>{children}</table></div>,
      img: ({src, alt}) => <Image src={src} alt={alt || '会话图片'} sizes="(max-width: 760px) 90vw, 780px"/>,
    }}>{text}</Markdown>;
});

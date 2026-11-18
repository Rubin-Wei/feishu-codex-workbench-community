export interface FileTarget {path:string;line?:number}

// Keep web URLs, anchors, and unsafe protocols out of the server file reader.
export function fileTarget(href:string):FileTarget|null {
 let value=href.trim();
 if(!value||value.startsWith('#')||value.startsWith('//'))return null;
 if(/^(?:https?|mailto|tel|data|javascript|vbscript):/i.test(value))return null;
 if(value.startsWith('file://')){
  try{const url=new URL(value);if(url.hostname&&url.hostname!=='localhost')return null;value=url.pathname+url.hash}catch{return null}
 }else if(value.startsWith('sandbox:/'))value=value.slice('sandbox:'.length);
 else if(/^[a-z][a-z\d+.-]*:/i.test(value)&&!/^.*:\d+(?::\d+)?$/.test(value))return null;
 if(/^[a-z][a-z\d+.-]*:\/\//i.test(value))return null;
 try{value=decodeURIComponent(value)}catch{return null}
 let line:number|undefined;
 const fragment=value.match(/#L(\d+)(?:C\d+)?(?:-L?\d+(?:C\d+)?)?$/i);
 if(fragment){line=Number(fragment[1]);value=value.slice(0,-fragment[0].length)}
 const suffix=value.match(/:(\d+)(?::\d+)?$/);
 if(suffix){line??=Number(suffix[1]);value=value.slice(0,-suffix[0].length)}
 if(/[\u0000-\u001f\u007f]/.test(value)||value.includes('?')||value.includes('#')||value.startsWith('//'))return null;
 if(!value||value.includes(':'))return null;
 return {path:value,...(line&&Number.isSafeInteger(line)?{line}:{})};
}

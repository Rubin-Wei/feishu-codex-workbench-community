import type {ModelOption} from '@shared/workbench';
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@client/src/components/ui/select';

const effortLabels:Record<string,string>={none:'无',minimal:'最低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最大',ultra:'超高'};
interface ModelPickerProps {
  models:ModelOption[];model:string;effort:string;currentModel?:string;currentEffort?:string;disabled:boolean;
  onChange:(model:string,effort:string)=>void;
}
export function ModelPicker({models,model,effort,currentModel,currentEffort,disabled,onChange}:ModelPickerProps){
  const selected=models.find(m=>m.id===(model==='inherit'?currentModel:model));
  return <div className="model-controls">
    <Select value={model} disabled={disabled} onValueChange={id=>onChange(id,id==='inherit'?'inherit':models.find(m=>m.id===id)?.defaultEffort||'inherit')}>
      <SelectTrigger size="sm" aria-label="选择模型"><SelectValue/></SelectTrigger>
      <SelectContent><SelectItem value="inherit">{currentModel?`沿用 · ${currentModel}`:'沿用会话模型'}</SelectItem>
        {models.map(m=><SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>)}
      </SelectContent>
    </Select>
    <Select value={effort} disabled={disabled||!selected} onValueChange={value=>onChange(model,value)}>
      <SelectTrigger size="sm" aria-label="选择推理强度"><SelectValue/></SelectTrigger>
      <SelectContent><SelectItem value="inherit">{currentEffort?`沿用 · ${effortLabels[currentEffort]||currentEffort}`:'沿用推理强度'}</SelectItem>
        {selected?.efforts.map(e=><SelectItem key={e} value={e}>{effortLabels[e]||e} · {e}</SelectItem>)}
      </SelectContent>
    </Select>
    <span>下次发送生效</span>
  </div>;
}

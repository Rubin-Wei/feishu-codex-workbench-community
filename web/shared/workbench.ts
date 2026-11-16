export interface Host {id:string;label:string;default_cwd:string;roots:string[]}
export interface Thread {id:string;name?:string;preview?:string;cwd:string;updatedAt?:number;model?:string;reasoningEffort?:string;status?:{type:string}}
export interface Message {id:string;role:string;text:string;clientId?:string}
export interface Job {id:string;host:string;thread:string;turn?:string;prompt:string;status:string;result:string;partial?:string;partialItems?:{id:string;text:string}[]}
export interface QueuedMessage {id:string;host:string;thread:string;prompt:string;mode:string;status:string;job?:string;message_id?:string;error?:string;paused?:string;model?:string;effort?:string}
export interface LiveSnapshot {revision:number;jobs:Job[];approvals:Approval[];queue:QueuedMessage[]}
export interface LiveReply {changed:boolean;revision:number;value?:LiveSnapshot}
export interface QuestionData {id:string;question:string;options?:{label:string;description?:string}[]}
export interface Approval {token:string;host:string;thread:string;reason?:string;command?:string;questions?:QuestionData[]}
export interface Catalog {threads?:Thread[];connected:boolean;syncing:boolean;updatedAt?:number;error?:string}
export interface ModelOption {id:string;label:string;efforts:string[];defaultEffort?:string}
export interface Snapshot {online:boolean;hosts:Host[];jobs:Job[];approvals:Approval[];queue?:QueuedMessage[];revision?:number;catalogs?:Record<string,Catalog>;models?:Record<string,ModelOption[]>;supervisor_model?:string;supervisor_effort?:string;controller?:string}
export interface History {thread:Thread|null;messages:Message[];nextCursor?:string}
export interface CachedHistory {cached:boolean;updatedAt?:number;value?:History}
export interface CommandReplies {
 models:ModelOption[];sessions:{data:Thread[];nextCursor:string|null};history:History;supervisor:History;
 directories:{path:string;directories:string[]};new_session:Thread;submit:Job;
 stop:unknown;reconcile:Job;approval:unknown;answer:unknown;image:unknown;
 enqueue:QueuedMessage;steer:QueuedMessage;cancel_queue:unknown;resume_queue:unknown;
}
export interface CommandPoll<T> {status:string;result:T & {error?:string}}

export type JsonObject = Record<string, unknown>;
export const COMMAND_ACTIONS = [
  'sessions', 'history', 'new_session', 'submit', 'directories', 'stop',
  'reconcile', 'approval', 'answer', 'image', 'supervisor', 'models',
  'enqueue','steer','cancel_queue','resume_queue','account','file_preview',
] as const;
export type CommandAction = (typeof COMMAND_ACTIONS)[number];
export interface CommandRequest { id: string; action: string; args: JsonObject }
export interface CommandResult { id: string; ok: boolean; value: unknown }
export interface CacheAck {host:string;thread:string;revision:string}
export interface CacheUpdate extends CacheAck {updatedAt:number;value:JsonObject}
export interface AgentRequest { snapshot?: JsonObject; results?: CommandResult[]; capacity?: number;cacheUpdates?:CacheUpdate[];live?:JsonObject }
export interface AgentResponse { acked: string[]; commands: CommandRequest[];cacheAcked:CacheAck[] }
export interface LoginRequest { username: string; password: string }

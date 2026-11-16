import { createHmac, pbkdf2, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
import { UnauthorizedException } from '@nestjs/common';
import type { Request } from 'express';
const derive = promisify(pbkdf2);
const SESSION_SECONDS = 90 * 86400;
interface Config {
  AUTH_USERNAME: string; AUTH_PASSWORD_HASH: string;
  AUTH_PASSWORD_SALT: string; AUTH_SESSION_SECRET: string;
}
function config(): Config {
  const c: Config = JSON.parse(process.env.WORKBENCH_AUTH || '{}');
  if (!c.AUTH_USERNAME || !/^[a-f0-9]{64}$/.test(c.AUTH_PASSWORD_HASH || '') ||
      !c.AUTH_PASSWORD_SALT || (c.AUTH_SESSION_SECRET || '').length < 32) {
    throw new Error('Workstation authentication is not configured');
  }
  return c;
}
export async function passwordMatches(username: string, password: string): Promise<boolean> {
  const c = config();
  const hash = await derive(password, c.AUTH_PASSWORD_SALT, 100000, 32, 'sha256');
  return timingSafeEqual(hash, Buffer.from(c.AUTH_PASSWORD_HASH, 'hex')) && username === c.AUTH_USERNAME;
}
export function signSession(): string {
  const c = config();
  const payload = Buffer.from(JSON.stringify({ user: c.AUTH_USERNAME, expires: Date.now() + SESSION_SECONDS * 1000 })).toString('base64url');
  return payload + '.' + createHmac('sha256', c.AUTH_SESSION_SECRET).update(payload).digest('hex');
}
export function requireOwner(req: Request): number {
  try {
    const value = (req.headers.cookie || '').split(';').map(x => x.trim()).find(x => x.startsWith('codex_session='))?.slice(14) || '';
    const [payload, signature, extra] = value.split('.');
    if (!payload || !/^[a-f0-9]{64}$/.test(signature || '') || extra) throw new Error('invalid');
    const c = config();
    const expected = createHmac('sha256', c.AUTH_SESSION_SECRET).update(payload).digest();
    if (!timingSafeEqual(expected, Buffer.from(signature, 'hex'))) throw new Error('invalid');
    const p = JSON.parse(Buffer.from(payload, 'base64url').toString());
    if (p.user !== c.AUTH_USERNAME || !(p.expires > Date.now())) throw new Error('expired');
    return p.expires;
  } catch { throw new UnauthorizedException('请先登录工作台'); }
}
export const sessionCookie = (value: string, clear = false): string =>
  `codex_session=${value}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${clear ? 0 : SESSION_SECONDS}`;

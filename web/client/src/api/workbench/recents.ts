const STORAGE_KEY = 'workbench-recent-sessions:v1';
const LIMIT = 8;

export interface RecentSession {host: string; thread: string; visitedAt: number}

function valid(value: unknown): value is RecentSession {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<RecentSession>;
  return typeof item.host === 'string' && /^[a-z0-9-]{1,40}$/.test(item.host) &&
    typeof item.thread === 'string' && /^[a-f0-9-]{36}$/.test(item.thread) &&
    typeof item.visitedAt === 'number' && Number.isFinite(item.visitedAt) && item.visitedAt >= 0;
}

export function readRecents(): RecentSession[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    if (!Array.isArray(value)) return [];
    const seen = new Set<string>();
    return value.filter(valid).sort((a, b) => b.visitedAt - a.visitedAt).filter(item => {
      const key = item.host + ':' + item.thread;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).slice(0, LIMIT);
  } catch { return []; }
}

export function visitSession(previous: RecentSession[], host: string, thread: string): RecentSession[] {
  const item: RecentSession = {host, thread, visitedAt: Date.now()};
  if (!valid(item)) return previous;
  const next = [item, ...previous.filter(old => old.host !== host || old.thread !== thread)].slice(0, LIMIT);
  // Only IDs and visit times are stored; titles and messages stay in the authenticated cache.
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* Storage is optional. */ }
  return next;
}

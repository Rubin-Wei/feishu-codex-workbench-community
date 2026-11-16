import type {Thread} from '@shared/workbench';

export interface ProjectGroup {path: string; name: string; threads: Thread[]; total: number}
export const projectName = (path: string): string => path.split('/').filter(Boolean).pop() || '/';

// Use the whole cwd as identity: same-named folders on different paths stay separate.
export function groupProjects(threads: Thread[], query = ''): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>();
  for (const thread of threads) {
    const path = thread.cwd.replace(/\/+$/, '') || '/';
    if (!groups.has(path)) groups.set(path, {path, name: projectName(path), threads: [], total: 0});
    const group = groups.get(path)!;
    group.threads.push(thread); group.total++;
  }
  const search = query.trim().toLocaleLowerCase();
  return [...groups.values()].map(group => ({...group,
    threads: group.path.toLocaleLowerCase().includes(search) ? group.threads : group.threads.filter(thread =>
      [thread.name, thread.preview, thread.id].some(value => value?.toLocaleLowerCase().includes(search))),
  })).filter(group => group.threads.length > 0);
}

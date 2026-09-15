export interface LiveJob {
  convId: string;
  thinking: boolean;
  statusText: string;
  userText: string;
  text: string;
  reasoning?: string;
  search?: { query: string; summary: string }[];
  file?: { filename: string; data: string; url?: string; canvas?: boolean };
}

export type LiveJobsMap = Record<string, LiveJob>;
export type LiveJobPatch = Partial<LiveJob>;

export function emptyJob(convId: string): LiveJob {
  return { convId, thinking: false, statusText: '', userText: '', text: '' };
}

export function upsertJob(jobs: LiveJobsMap, convId: string, patch: LiveJobPatch): LiveJobsMap {
  const current = jobs[convId] || emptyJob(convId);
  return { ...jobs, [convId]: { ...current, ...patch, convId } };
}

export function dropJob(jobs: LiveJobsMap, convId?: string): LiveJobsMap {
  if (!convId || !jobs[convId]) return jobs;
  const next = { ...jobs };
  delete next[convId];
  return next;
}

export function jobFromSnapshot(job: {
  conversation_id: string;
  user_text?: string;
  status_text?: string;
  text?: string;
  reasoning?: string;
  search?: { query: string; summary: string }[];
  thinking?: boolean;
}): LiveJob {
  return {
    convId: job.conversation_id,
    thinking: job.thinking !== false,
    statusText: job.status_text || '',
    userText: job.user_text || '',
    text: job.text || '',
    reasoning: job.reasoning || undefined,
    search: job.search?.length ? job.search : undefined,
  };
}

export function jobsFromSnapshot(list?: Array<{
  conversation_id: string;
  user_text?: string;
  status_text?: string;
  text?: string;
  reasoning?: string;
  search?: { query: string; summary: string }[];
  thinking?: boolean;
}> | null): LiveJobsMap {
  const next: LiveJobsMap = {};
  for (const job of list || []) {
    if (!job?.conversation_id) continue;
    next[job.conversation_id] = jobFromSnapshot(job);
  }
  return next;
}

/** Keep local HTTP jobs (image generate/edit) when a WS snapshot has not heard of them.
 *  Also keep a richer live status/search the snapshot has not caught up with yet. */
export function mergeRemoteJobs(local: LiveJobsMap, remoteList?: Array<{
  conversation_id: string;
  user_text?: string;
  status_text?: string;
  text?: string;
  reasoning?: string;
  search?: { query: string; summary: string }[];
  thinking?: boolean;
}> | null): LiveJobsMap {
  const next = jobsFromSnapshot(remoteList);
  for (const [id, job] of Object.entries(local)) {
    if (!job.thinking) continue;
    const remote = next[id];
    if (!remote) {
      next[id] = job;
      continue;
    }
    next[id] = {
      ...remote,
      thinking: true,
      userText: job.userText || remote.userText,
      statusText: (job.statusText?.length || 0) >= (remote.statusText?.length || 0) ? job.statusText : remote.statusText,
      text: (job.text?.length || 0) >= (remote.text?.length || 0) ? job.text : remote.text,
      reasoning: (job.reasoning?.length || 0) >= (remote.reasoning?.length || 0) ? job.reasoning : remote.reasoning,
      search: (job.search?.length || 0) >= (remote.search?.length || 0) ? job.search : remote.search,
    };
  }
  return next;
}

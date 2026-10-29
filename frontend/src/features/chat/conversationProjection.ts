import type { DisplayMessage } from './ChatWindow';
import type { LiveJob } from './liveJobs';
import { isClarifyMessage, splitSearch } from './clarify';

export type HistoryMessage = Omit<DisplayMessage, 'role'> & { role: string };
export type PendingReply = Pick<LiveJob, 'userText' | 'text' | 'thinking' | 'file' | 'reasoning' | 'search'> & { convId?: string };
type Projection = { messages: DisplayMessage[]; recovered: boolean; persistence: 'none' | 'drop' | 'keep-file' };

/** Pure reconciliation of persisted history, a live reply and durable errors. */
export function projectConversation({ messages, pending, conversationId, regeneratingId, error, imageBaseline, socketOpen, httpJob }: {
  messages: HistoryMessage[]; pending: PendingReply; conversationId: string; regeneratingId: number | null;
  error?: string; imageBaseline?: Set<string>; socketOpen: boolean; httpJob: boolean;
}): Projection {
  const base: DisplayMessage[] = messages
    .filter(message => message.role === 'user' || message.role === 'assistant')
    .filter(message => regeneratingId == null || message.message_id !== regeneratingId)
    .map(message => ({ id: message.id, message_id: message.message_id, role: message.role as DisplayMessage['role'],
      content: message.content, attachment: message.attachment, search: message.search, author: message.author, mine: message.mine }));
  const withError = (items: DisplayMessage[]) => error
    ? [...items, { id: `job-err-${conversationId}`, role: 'assistant' as const, content: error }]
    : items;
  if (pending.convId !== conversationId) return { messages: withError(base), recovered: false, persistence: 'none' };

  const lastUser = [...base].reverse().find(message => message.role === 'user');
  const persistedNewUser = Boolean(pending.userText && imageBaseline && base.some(message => (
    message.role === 'user' && message.content === pending.userText && !imageBaseline.has(message.id)
  )));
  const addUser = pending.userText && (lastUser?.content !== pending.userText || (imageBaseline && !persistedNewUser));
  const withUser: DisplayMessage[] = addUser
    ? [...base, { id: 'pending-user', role: 'user', content: pending.userText, mine: true }]
    : base;
  const lastAssistant = [...withUser].reverse().find(message => message.role === 'assistant');
  const pendingUserAt = pending.userText ? base.map(message => message.role === 'user' ? message.content : '').lastIndexOf(pending.userText) : -1;
  const finalAnswer = (message: DisplayMessage) => message.role === 'assistant' && !message.attachment?.interim;
  const recoveredAnswer = imageBaseline
    ? base.some(message => finalAnswer(message) && !imageBaseline.has(message.id))
    : pendingUserAt >= 0 && base.slice(pendingUserAt + 1).some(finalAnswer);
  // The saved reply is the result. Hiding it until a "done" event arrives left the
  // chat on "Думаю" after the archive was already stored; Stop only uncovered it.
  const holdSavedAnswer = pending.thinking && socketOpen && !httpJob && !recoveredAnswer;
  const lastUserAt = withUser.map(message => message.role).lastIndexOf('user');
  const view = holdSavedAnswer
    ? withUser.filter((message, index) => !(index > lastUserAt && message.role === 'assistant' && !message.attachment?.interim))
    : withUser;
  const pendingClarify = splitSearch(pending.search).questions.length > 0;
  const withAssistant: DisplayMessage[] = (pending.text || pendingClarify)
    && !isClarifyMessage(lastAssistant?.search) && lastAssistant?.content !== pending.text
    ? [...view, { id: 'pending-assistant', role: 'assistant', content: pending.text, reasoning: pending.reasoning, search: pending.search }]
    : view;
  const last = withAssistant.at(-1);
  const withFile: DisplayMessage[] = !pending.file ? withAssistant : last?.role === 'assistant'
    ? withAssistant.map((message, index) => index === withAssistant.length - 1 ? { ...message, file: pending.file } : message)
    : [...withAssistant, { id: 'pending-file', role: 'assistant', content: `Файл готов: ${pending.file.filename}`, file: pending.file,
      ...(withAssistant === view ? { reasoning: pending.reasoning, search: pending.search } : {}) }];
  const persistence = pending.text && lastAssistant?.content === pending.text
    ? lastAssistant.attachment?.url || !pending.file ? 'drop' : 'keep-file'
    : !pending.thinking && lastAssistant?.attachment?.url && pending.file ? 'drop' : 'none';
  return { messages: pending.thinking ? withFile : withError(withFile),
    recovered: Boolean(pending.thinking && recoveredAnswer && !holdSavedAnswer), persistence };
}

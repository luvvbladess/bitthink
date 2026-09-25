export interface QueuedMessage {
  type: string;
  payload: Record<string, any>;
}

const queue: QueuedMessage[] = [];

export function enqueueSend(message: QueuedMessage) {
  queue.push(message);
}

export function drainSends(): QueuedMessage[] {
  return queue.splice(0);
}

export function clearPendingSends() {
  queue.splice(0, queue.length);
}

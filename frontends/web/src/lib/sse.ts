import type { ChatStreamChunk } from '../pages/Chat/types';

export interface StreamHandlers {
  onChunk: (chunk: ChatStreamChunk) => void;
}

/**
 * POST to the SSE chat endpoint and invoke `handlers.onChunk` per parsed
 * chunk. Mirrors the webcomponent `ChatbotApiClient.streamChat` protocol:
 * lines prefixed with `data: `, `[DONE]` ends the stream, unparseable
 * lines are skipped with a warning.
 */
export async function streamChat(
  body: Record<string, unknown>,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch('/api/vanna/v2/chat_sse', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    credentials: 'include',
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        const data = line.slice(6).trim();
        if (data === '[DONE]') return;

        try {
          handlers.onChunk(JSON.parse(data) as ChatStreamChunk);
        } catch (e) {
          console.warn('Failed to parse SSE chunk:', data, e);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
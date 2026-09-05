/** Chat message shown in the UI. */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  /** Accumulated simple text payload of the assistant reply. */
  content: string;
  /** Rich components received for this message. */
  rich: RichComponent[];
  status: 'streaming' | 'done' | 'error';
  errorDetail?: string;
}

/** Serialized rich component from the backend (`ChatStreamChunk.rich`). */
export interface RichComponent {
  id?: string;
  type: string;
  lifecycle?: string;
  children?: string[];
  timestamp?: string;
  visible?: boolean;
  interactive?: boolean;
  data: Record<string, any>;
}

/** One SSE chunk of the POST /api/vanna/v2/chat_sse stream. */
export interface ChatStreamChunk {
  rich: RichComponent;
  simple?: Record<string, any> | null;
  conversation_id: string;
  request_id: string;
  timestamp: number;
}

/**
 * Collapse component updates sharing the same id (lifecycle create/update
 * sequences) to the latest payload for replay rendering.
 */
export function dedupeRich(rich: RichComponent[]): RichComponent[] {
  const byId = new Map<string, RichComponent>();
  for (const comp of rich) {
    byId.set(comp.id ?? `${comp.type}_${byId.size}`, comp);
  }
  return [...byId.values()];
}
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ConversationMeta } from '../../lib/api';
import { streamChat } from '../../lib/sse';
import { ChatMessage, ChatStreamChunk, RichComponent } from './types';

function makeId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function mapStoredRich(rich?: Record<string, any>[]): RichComponent[] {
  return (rich ?? []).map((r) => ({
    id: r.id ?? makeId('rc'),
    type: r.type ?? 'unknown',
    visible: r.visible,
    data: r.data ?? {},
  }));
}

/** Live input updates pushed by the backend (ChatInputUpdateComponent). */
export interface ChatInputHint {
  placeholder?: string;
  value?: string;
}

export interface ChatSession {
  conversationId: string | null;
  messages: ChatMessage[];
  sending: boolean;
  conversations: ConversationMeta[];
  loadingConversation: boolean;
  inputHint: ChatInputHint | null;
  sendMessage: (text: string) => void;
  stop: () => void;
  newConversation: () => void;
  openConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  refreshConversations: () => void;
  retry: (failedMessageId: string) => void;
}

/**
 * Chat session state: draft conversations (conversationId === null, never
 * persisted), streaming, history loading and per-business listing.
 */
export function useChatSession(businessId: string | undefined): ChatSession {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [inputHint, setInputHint] = useState<ChatInputHint | null>(null);
  const [loadingConversation, setLoadingConversation] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  conversationIdRef.current = conversationId;

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.conversations(businessId));
    } catch {
      setConversations([]);
    }
  }, [businessId]);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const openConversation = useCallback(
    async (id: string) => {
      stop();
      setLoadingConversation(true);
      try {
        const conv = await api.conversation(id);
        setConversationId(conv.id);
        setMessages(
          conv.messages.map((m) => ({
            id: makeId('msg'),
            role: (m.role === 'user' ? 'user' : 'assistant') as ChatMessage['role'],
            content: m.content,
            rich: mapStoredRich(m.rich),
            status: 'done',
          }))
        );
        setInputHint(null);
      } catch {
        setMessages([]);
        setConversationId(null);
      } finally {
        setLoadingConversation(false);
      }
    },
    [stop]
  );

  const newConversation = useCallback(() => {
    stop();
    setConversationId(null);
    setMessages([]);
    setInputHint(null);
  }, [stop]);

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        if (conversationIdRef.current === id) {
          newConversation();
        }
      } finally {
        void refreshConversations();
      }
    },
    [newConversation, refreshConversations]
  );

  const startStream = useCallback(
    async (text: string, attachUser: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setSending(true);

      const userMessage: ChatMessage = {
        id: makeId('msg'),
        role: 'user',
        content: text,
        rich: [],
        status: 'done',
      };
      const assistantId = makeId('msg');
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        rich: [],
        status: 'streaming',
      };
      setMessages((prev) =>
        attachUser ? [...prev, userMessage, assistantMessage] : [...prev, assistantMessage]
      );

      const patchAssistant = (patch: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? patch(m) : m)));
      };

      let boundConversationId = conversationIdRef.current;
      let streamFailed = false;

      try {
        await streamChat(
          {
            message: text,
            conversation_id: boundConversationId ?? undefined,
            business_id: businessId,
          },
          {
            onChunk: (chunk: ChatStreamChunk) => {
              // A6: backend error frames ({type:'error',data:{message}}) carry
              // none of the ChatStreamChunk payload fields; detect them first.
              const errorFrame = chunk as unknown as {
                type?: string;
                data?: { message?: unknown };
              };
              if (errorFrame.type === 'error') {
                streamFailed = true;
                patchAssistant((m) => ({
                  ...m,
                  status: 'error',
                  errorDetail:
                    typeof errorFrame.data?.message === 'string'
                      ? errorFrame.data.message
                      : 'request failed',
                }));
                return;
              }
              if (chunk.conversation_id && !boundConversationId) {
                boundConversationId = chunk.conversation_id;
                conversationIdRef.current = chunk.conversation_id;
                setConversationId(chunk.conversation_id);
              }
              const simpleText = (chunk.simple as { text?: unknown } | null)?.text;
              if (typeof simpleText === 'string') {
                patchAssistant((m) => ({ ...m, content: m.content + simpleText }));
              }
              if (chunk.rich) {
                patchAssistant((m) => ({ ...m, rich: [...m.rich, chunk.rich] }));
                if (chunk.rich.type === 'chat_input_update') {
                  const data = chunk.rich.data ?? {};
                  setInputHint({
                    placeholder:
                      typeof data.placeholder === 'string' ? data.placeholder : undefined,
                    value: typeof data.value === 'string' ? data.value : undefined,
                  });
                }
              }
            },
          },
          controller.signal
        );
        if (!streamFailed) {
          patchAssistant((m) => ({ ...m, status: 'done' }));
        }
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          patchAssistant((m) =>
            m.content || m.rich.length > 0
              ? { ...m, status: 'done' }
              : { ...m, status: 'error', errorDetail: 'generation stopped' }
          );
        } else {
          // A6: detect unauthenticated responses by the HTTP status code
          // prefix (e.g. "HTTP 401: Unauthorized"), never by error text.
          const statusPrefix = /^HTTP (\d{3})\b/.exec(e?.message ?? '')?.[1] ?? '';
          const authError = statusPrefix === '401' || statusPrefix === '403';
          patchAssistant((m) => ({
            ...m,
            status: 'error',
            errorDetail: authError ? 'authentication required' : e?.message ?? 'request failed',
          }));
        }
      } finally {
        setSending(false);
        abortRef.current = null;
        void refreshConversations();
      }
    },
    [businessId, refreshConversations]
  );

  // Starter UI: on a fresh draft (no conversation, no messages), request
  // the backend welcome card. Starter requests never bind a conversation
  // id (the backend does not persist them) and never persist locally.
  useEffect(() => {
    if (conversationId !== null || messages.length > 0 || sending) return;

    const controller = new AbortController();
    abortRef.current = controller;

    const starterId = makeId('msg');
    setMessages([
      { id: starterId, role: 'assistant', content: '', rich: [], status: 'streaming' },
    ]);

    const patchStarter = (patch: (m: ChatMessage) => ChatMessage) => {
      setMessages((prev) => prev.map((m) => (m.id === starterId ? patch(m) : m)));
    };

    let starterFailed = false;
    void streamChat(
      { message: '', business_id: businessId, metadata: { starter_ui_request: true } },
      {
        onChunk: (chunk: ChatStreamChunk) => {
          const errorFrame = chunk as unknown as {
            type?: string;
            data?: { message?: unknown };
          };
          if (errorFrame.type === 'error') {
            starterFailed = true;
            patchStarter((m) => ({
              ...m,
              status: 'error',
              errorDetail:
                typeof errorFrame.data?.message === 'string'
                  ? errorFrame.data.message
                  : 'request failed',
            }));
            return;
          }
          if (chunk.rich) {
            patchStarter((m) => ({ ...m, rich: [...m.rich, chunk.rich] }));
          }
        },
      },
      controller.signal
    )
      .then(() => {
        if (!starterFailed) {
          patchStarter((m) => ({ ...m, status: 'done' }));
        }
      })
      .catch((e: any) => {
        if (e?.name === 'AbortError') {
          patchStarter((m) => ({ ...m, status: 'done' }));
        } else {
          patchStarter((m) => ({ ...m, status: 'error', errorDetail: e?.message }));
        }
      })
      .finally(() => {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      });
  }, [conversationId, businessId, messages.length, sending]);

  const sendMessage = useCallback(
    (text: string) => {
      void startStream(text, true);
    },
    [startStream]
  );

  const retry = useCallback(
    (failedMessageId: string) => {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user');
      if (!lastUser) return;
      setMessages((prev) => prev.filter((m) => m.id !== failedMessageId));
      void startStream(lastUser.content, false);
    },
    [messages, startStream]
  );

  return {
    conversationId,
    messages,
    sending,
    conversations,
    loadingConversation,
    inputHint,
    sendMessage,
    stop,
    newConversation,
    openConversation,
    deleteConversation,
    refreshConversations,
    retry,
  };
}
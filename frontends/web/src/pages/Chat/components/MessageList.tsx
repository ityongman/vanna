import { useEffect, useRef, useState } from 'react';
import { Button, Spin } from 'antd';
import { ArrowDownOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';
import { ChatMessage } from '../types';
import MessageBubble from './MessageBubble';

export interface MessageListProps {
  messages: ChatMessage[];
  loading?: boolean;
  onSendAction?: (action: string) => void;
  onRetry?: (failedMessageId: string) => void;
}

/** Chat message flow with auto-scroll and a "back to bottom" button. */
export default function MessageList({ messages, loading, onSendAction, onRetry }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollDown, setShowScrollDown] = useState(false);
  // A9: whether the user is following the bottom (updated on scroll).
  const stickRef = useRef(true);
  // A9: previous loading state, to detect "history finished loading".
  const prevLoadingRef = useRef<boolean | undefined>(undefined);

  const scrollToBottom = (smooth: boolean) => {
    const el = containerRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  // Track the scroll position: show the scroll-down button only while the
  // user is away from the bottom, and remember whether they follow it.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowScrollDown(dist > 80);
      stickRef.current = dist < 80;
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // New chunks follow the bottom only while the user is already there, so
  // streaming never yanks users who scrolled up to read.
  useEffect(() => {
    if (stickRef.current) scrollToBottom(false);
  }, [messages]);

  // After a conversation finishes loading, always jump to the newest message.
  useEffect(() => {
    if (prevLoadingRef.current && !loading) {
      scrollToBottom(false);
    }
    prevLoadingRef.current = loading;
  }, [loading]);

  return (
    <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 16 }}>
          <Spin />
        </div>
      )}
      <div ref={containerRef} style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} onSendAction={onSendAction} onRetry={onRetry} />
        ))}
      </div>
      {showScrollDown && (
        <Button
          shape="circle"
          icon={<ArrowDownOutlined />}
          title={t('common', 'chat.scrollToBottom', '回到底部')}
          style={{ position: 'absolute', right: 24, bottom: 16 }}
          onClick={() => {
            scrollToBottom(true);
            setShowScrollDown(false);
          }}
        />
      )}
    </div>
  );
}
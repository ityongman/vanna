import { useEffect, useRef } from 'react';
import { useParams } from 'react-router';
import { useAuth } from '../../lib/auth';

function Chat() {
  const { businessId } = useParams();
  const { user } = useAuth();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Load the web component if not already defined
    if (!customElements.get('chatbot-chat')) {
      const script = document.createElement('script');
      script.type = 'module';
      script.src = '/static/chatbot-components.js';
      document.head.appendChild(script);
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    // Clear and create the chat element
    containerRef.current.innerHTML = '';
    const chatEl = document.createElement('chatbot-chat');
    chatEl.setAttribute('api-base', '');
    chatEl.setAttribute('sse-endpoint', '/api/vanna/v2/chat_sse');
    chatEl.setAttribute('ws-endpoint', '/api/vanna/v2/chat_websocket');
    chatEl.setAttribute('poll-endpoint', '/api/vanna/v2/chat_poll');
    chatEl.setAttribute('business-id', businessId || '');
    chatEl.setAttribute('title', 'Vanna AI');
    chatEl.setAttribute('subtitle', user?.email || '');
    chatEl.style.height = '100%';
    containerRef.current.appendChild(chatEl);
  }, [businessId, user?.email]);

  return (
    <div ref={containerRef} style={{ height: 'calc(100vh - 120px)', padding: '16px' }} />
  );
}

export default Chat;

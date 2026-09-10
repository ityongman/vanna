import { useState } from 'react';
import { Layout } from 'antd';
import { useParams } from 'react-router';
import { useChatSession } from './useChatSession';
import ConversationSidebar from './components/ConversationSidebar';
import MessageList from './components/MessageList';
import Composer from './components/Composer';

const { Content } = Layout;

function ChatContent({ businessId }: { businessId: string | undefined }) {
  const chat = useChatSession(businessId);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout style={{ flex: 1, minHeight: 0, flexDirection: 'row' }}>
      <div
        style={{
          width: collapsed ? 64 : 280,
          flex: 'none',
          height: '100%',
          overflow: 'hidden',
          borderRight: '1px solid #f0f0f0',
          background: '#fff',
          transition: 'width 0.2s ease',
        }}
      >
        <ConversationSidebar
          conversations={chat.conversations}
          activeId={chat.conversationId}
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
          onSelect={(id) => void chat.openConversation(id)}
          onNew={chat.newConversation}
          onDelete={(id) => void chat.deleteConversation(id)}
        />
      </div>
      <Layout>
        <Content style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <MessageList
            messages={chat.messages}
            loading={chat.loadingConversation}
            onSendAction={(action: string) => chat.sendMessage(action)}
            onRetry={chat.retry}
          />
          <Composer
            sending={chat.sending}
            placeholder={chat.inputHint?.placeholder}
            value={chat.inputHint?.value}
            onSend={chat.sendMessage}
            onStop={chat.stop}
          />
        </Content>
      </Layout>
    </Layout>
  );
}

function Chat() {
  const { businessId } = useParams();
  return <ChatContent key={businessId} businessId={businessId} />;
}

export default Chat;
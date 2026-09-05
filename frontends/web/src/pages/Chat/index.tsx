import { useState } from 'react';
import { Button, Layout } from 'antd';
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { useParams } from 'react-router';
import { t } from '../../i18n';
import { useAuth } from '../../lib/auth';
import { useChatSession } from './useChatSession';
import ConversationSidebar from './components/ConversationSidebar';
import MessageList from './components/MessageList';
import Composer from './components/Composer';

const { Sider, Content } = Layout;

function ChatContent({ businessId }: { businessId: string | undefined }) {
  const { user } = useAuth();
  const chat = useChatSession(businessId);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout style={{ height: 'calc(100vh - 120px)' }}>
      <Sider
        theme="light"
        width={280}
        collapsedWidth={0}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        trigger={null}
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <ConversationSidebar
          conversations={chat.conversations}
          activeId={chat.conversationId}
          onSelect={(id) => void chat.openConversation(id)}
          onNew={chat.newConversation}
          onDelete={(id) => void chat.deleteConversation(id)}
        />
      </Sider>
      <Layout>
        <Content style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ padding: '4px 8px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center' }}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((v) => !v)}
              title={t('common', 'chat.toggleSidebar', '切换会话列表')}
            />
            <span style={{ marginLeft: 8, color: '#1677ff' }}>{user?.email || ''}</span>
          </div>
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
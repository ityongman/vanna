import { useMemo, useState } from 'react';
import { Button, Empty, Input, List, Popconfirm, Typography } from 'antd';
import { DeleteOutlined, MessageOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { ConversationMeta } from '../../../lib/api';
import { t } from '../../../i18n';

const { Text } = Typography;

function conversationTitle(conv: ConversationMeta): string {
  return (
    conv.metadata?.title ||
    conv.messages?.[0]?.content?.slice(0, 40) ||
    t('common', 'chat.defaultTitle', '新对话')
  );
}

export interface ConversationSidebarProps {
  conversations: ConversationMeta[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: ConversationSidebarProps) {
  const [keyword, setKeyword] = useState('');

  const filtered = useMemo(() => {
    const sorted = [...conversations].sort(
      (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)
    );
    const kw = keyword.trim().toLowerCase();
    if (!kw) return sorted;
    return sorted.filter((c) => conversationTitle(c).toLowerCase().includes(kw));
  }, [conversations, keyword]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12, gap: 12 }}>
      <Button type="primary" block icon={<PlusOutlined />} onClick={onNew}>
        {t('common', 'chat.newConversation', '新建对话')}
      </Button>
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder={t('common', 'chat.searchPlaceholder', '搜索会话')}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t('common', 'chat.emptyList', '暂无会话')}
          />
        ) : (
          <List
            size="small"
            rowKey={(c) => c.id}
            dataSource={filtered}
            renderItem={(conv) => {
              const active = conv.id === activeId;
              return (
                <List.Item
                  onClick={() => onSelect(conv.id)}
                  style={{
                    cursor: 'pointer',
                    borderRadius: 8,
                    padding: '8px 12px',
                    background: active ? '#e6f4ff' : 'transparent',
                    border: 'none',
                  }}
                  actions={[
                    <Popconfirm
                      key="del"
                      title={t('common', 'chat.deleteConfirm', '确认删除该会话？')}
                      onConfirm={() => onDelete(conv.id)}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<MessageOutlined style={{ fontSize: 16, marginTop: 4 }} />}
                    title={
                      <Text strong={active} ellipsis={{ tooltip: conversationTitle(conv) }}>
                        {conversationTitle(conv)}
                      </Text>
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </div>
    </div>
  );
}
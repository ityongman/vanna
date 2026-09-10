import { useMemo, useRef, useState } from 'react';
import { Button, Empty, Input, List, Popconfirm, Tooltip, Typography } from 'antd';
import type { InputRef } from 'antd';
import {
  DeleteOutlined,
  FormOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { ConversationMeta } from '../../../lib/api';
import { t } from '../../../i18n';

const { Text } = Typography;

function conversationTitle(conv: ConversationMeta): string {
  return (
    conv.metadata?.title ||
    conv.messages?.[0]?.content?.slice(0, 40) ||
    t('common', 'chat.defaultTitle', '新聊天')
  );
}

export interface ConversationSidebarProps {
  conversations: ConversationMeta[];
  activeId: string | null;
  collapsed: boolean;
  onToggle: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export default function ConversationSidebar({
  conversations,
  activeId,
  collapsed,
  onToggle,
  onSelect,
  onNew,
  onDelete,
}: ConversationSidebarProps) {
  const [keyword, setKeyword] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<InputRef>(null);

  const filtered = useMemo(() => {
    const sorted = [...conversations].sort(
      (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)
    );
    const kw = keyword.trim().toLowerCase();
    if (!kw) return sorted;
    return sorted.filter((c) => conversationTitle(c).toLowerCase().includes(kw));
  }, [conversations, keyword]);

  // 折叠态：顶部为“打开侧边栏”按钮，下方 3 个图标（新聊天 / 搜索 / 最近聊天）
  if (collapsed) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          height: '100%',
          paddingTop: 12,
          gap: 4,
        }}
      >
        <Tooltip title={t('common', 'chat.openSidebar', '打开侧边栏')} placement="right">
          <Button
            type="text"
            icon={<MenuUnfoldOutlined style={{ fontSize: 18 }} />}
            onClick={onToggle}
            style={{ marginBottom: 4 }}
          />
        </Tooltip>
        <Tooltip title={t('common', 'chat.newChat', '新聊天')} placement="right">
          <Button
            type="text"
            icon={<FormOutlined style={{ fontSize: 18 }} />}
            onClick={onNew}
          />
        </Tooltip>
        <Tooltip title={t('common', 'chat.search', '搜索')} placement="right">
          <Button
            type="text"
            icon={<SearchOutlined style={{ fontSize: 18 }} />}
            onClick={() => {
              onToggle();
              setSearchOpen(true);
              setTimeout(() => searchRef.current?.focus(), 0);
            }}
          />
        </Tooltip>
        <Tooltip title={t('common', 'chat.recentChats', '最近聊天')} placement="right">
          <Button
            type="text"
            icon={<HistoryOutlined style={{ fontSize: 18 }} />}
            onClick={onToggle}
          />
        </Tooltip>
      </div>
    );
  }

  // 展开态：顶部 [标题]…[搜索][关闭侧边栏] / 新聊天入口 / 最近分组
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '8px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 16, fontWeight: 600, color: 'rgba(0,0,0,0.88)' }}>Vanna</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Tooltip title={t('common', 'chat.search', '搜索')} placement="bottom">
            <Button
              type="text"
              icon={<SearchOutlined style={{ fontSize: 16 }} />}
              onClick={() => {
                setSearchOpen((v) => !v);
                setTimeout(() => searchRef.current?.focus(), 0);
              }}
            />
          </Tooltip>
          <Tooltip title={t('common', 'chat.closeSidebar', '关闭侧边栏')} placement="bottom">
            <Button type="text" icon={<MenuFoldOutlined style={{ fontSize: 16 }} />} onClick={onToggle} />
          </Tooltip>
        </div>
      </div>
      {searchOpen && (
        <Input
          ref={searchRef}
          allowClear
          size="small"
          prefix={<SearchOutlined />}
          placeholder={t('common', 'chat.searchPlaceholder', '搜索会话')}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ marginTop: 8 }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setSearchOpen(false);
              setKeyword('');
            }
          }}
        />
      )}
      <Button
        type="text"
        block
        icon={<FormOutlined />}
        onClick={onNew}
        style={{ marginTop: 8, justifyContent: 'flex-start', fontWeight: 500, height: 40 }}
      >
        {t('common', 'chat.newChat', '新聊天')}
      </Button>
      <Text type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 4 }}>
        {t('common', 'chat.recent', '最近')}
      </Text>
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
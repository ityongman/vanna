import { Alert, Avatar, Button, Space, Spin } from 'antd';
import { ReloadOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';
import { AUTH_ERROR_DETAIL, ChatMessage, dedupeRich } from '../types';
import RichRenderer from './renderers/RichRenderer';

export interface MessageBubbleProps {
  message: ChatMessage;
  onSendAction?: (action: string) => void;
  onRetry?: (failedMessageId: string) => void;
}

/** Single chat bubble: user right / assistant left with rich content. */
export default function MessageBubble({ message, onSendAction, onRetry }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexDirection: isUser ? 'row-reverse' : 'row' }}>
      <Avatar
        size={32}
        icon={isUser ? <UserOutlined /> : <RobotOutlined />}
        style={{ flexShrink: 0, background: isUser ? '#1677ff' : '#52c41a' }}
      />
      <div style={{ maxWidth: '78%', minWidth: 0 }}>
        {isUser ? (
          <div
            style={{
              background: '#1677ff',
              color: '#fff',
              borderRadius: 12,
              padding: '8px 14px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              display: 'inline-block',
            }}
          >
            {message.content}
          </div>
        ) : (
          <Space direction="vertical" size={8} style={{ width: '100%', display: 'flex' }}>
            {dedupeRich(message.rich).map((comp, i) => (
              <RichRenderer key={comp.id ?? `${comp.type}_${i}`} component={comp} onSendAction={onSendAction} />
            ))}
            {message.status === 'streaming' && <Spin size="small" />}
            {message.status === 'error' && (
              <Alert
                type="error"
                showIcon
                message={
                  message.errorDetail === AUTH_ERROR_DETAIL
                    ? t('common', 'chat.authenticationRequired', '登录已过期，请重新登录')
                    : message.content || message.errorDetail || t('common', 'chat.generationFailed', '生成失败')
                }
                action={
                  onRetry &&
                  message.errorDetail !== AUTH_ERROR_DETAIL && (
                    <Button size="small" icon={<ReloadOutlined />} onClick={() => onRetry(message.id)}>
                      {t('common', 'chat.retry', '重试')}
                    </Button>
                  )
                }
              />
            )}
          </Space>
        )}
      </div>
    </div>
  );
}
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button, Card, Space, Typography } from 'antd';
import type { RichComponent } from '../../types';

const { Paragraph } = Typography;

interface CardAction {
  label?: string;
  action?: string;
  variant?: string;
}

/** CardComponent renderer (backend starter card & status cards). */
export default function CardView({
  component,
  onSendAction,
}: {
  component: RichComponent;
  onSendAction?: (action: string) => void;
}) {
  const data = component.data ?? {};
  const actions = (data.actions ?? []) as CardAction[];

  return (
    <Card
      size="small"
      style={{ marginTop: 8 }}
      title={
        <span>
          {data.icon ? `${data.icon} ` : ''}
          {data.title ?? ''}
        </span>
      }
      extra={
        actions.length > 0 && (
          <Space>
            {actions.map((act, i) => (
              <Button
                key={i}
                size="small"
                type={act.variant === 'secondary' ? 'default' : 'primary'}
                onClick={() => {
                  if (act.action) onSendAction?.(act.action);
                }}
              >
                {act.label ?? act.action}
              </Button>
            ))}
          </Space>
        )
      }
    >
      {data.markdown ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(data.content ?? '')}</ReactMarkdown>
      ) : (
        <Paragraph style={{ marginBottom: 0 }}>{data.content}</Paragraph>
      )}
    </Card>
  );
}
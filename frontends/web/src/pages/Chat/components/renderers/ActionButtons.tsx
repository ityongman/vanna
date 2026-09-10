import { Button, Space } from 'antd';
import type { RichComponent } from '../../types';

function variantToType(variant?: string) {
  if (variant === 'secondary') return 'default';
  if (variant === 'ghost' || variant === 'link') return 'text';
  return 'primary';
}

/** ButtonComponent / ButtonGroupComponent renderer. */
export default function ActionButtons({
  component,
  onSendAction,
}: {
  component: RichComponent;
  onSendAction?: (action: string) => void;
}) {
  const data = component.data ?? {};
  const buttons: Record<string, any>[] =
    component.type === 'button_group'
      ? ((data.buttons ?? []) as Record<string, any>[])
      : [data as Record<string, any>];

  return (
    <Space wrap style={{ marginTop: 8 }}>
      {buttons.map((btn, i) => (
        <Button
          key={i}
          type={variantToType(btn?.variant) as any}
          size={btn?.size === 'large' ? 'large' : 'small'}
          disabled={!!btn?.disabled}
          onClick={() => {
            if (typeof btn?.action === 'string') onSendAction?.(btn.action);
          }}
        >
          {btn?.icon && btn?.icon_position !== 'right' ? `${btn.icon} ` : ''}
          {btn?.label}
          {btn?.icon && btn?.icon_position === 'right' ? ` ${btn.icon}` : ''}
        </Button>
      ))}
    </Space>
  );
}
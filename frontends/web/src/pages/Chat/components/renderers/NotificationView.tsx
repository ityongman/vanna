import { Alert } from 'antd';
import type { RichComponent } from '../../types';

function levelToAlert(level?: string) {
  if (level === 'success') return 'success';
  if (level === 'warning') return 'warning';
  if (level === 'error') return 'error';
  return 'info';
}

/** NotificationComponent renderer (backend feedback level: success/info/warning/error). */
export default function NotificationView({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  const level = levelToAlert(String(data.level ?? ''));
  return (
    <Alert
      style={{ marginTop: 8 }}
      type={level as any}
      showIcon
      message={<span>{data.icon ? `${data.icon} ` : ''}{data.title || data.message}</span>}
      description={data.title ? data.message : undefined}
    />
  );
}

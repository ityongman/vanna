import { Alert } from 'antd';
import type { RichComponent } from '../../types';

function statusToAlert(status?: string) {
  if (status === 'success' || status === 'completed') return 'success';
  if (status === 'warning') return 'warning';
  if (status === 'error' || status === 'failed') return 'error';
  return 'info';
}

/** StatusCardComponent renderer. */
export default function StatusCardView({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  return (
    <Alert
      style={{ marginTop: 8 }}
      type={statusToAlert(String(data.status ?? '')) as any}
      message={<span>{data.icon ? `${data.icon} ` : ''}{data.title}</span>}
      description={data.description}
    />
  );
}
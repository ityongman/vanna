import { Collapse, Typography } from 'antd';
import type { RichComponent } from '../../types';

/** Fallback for unknown component types: collapsible JSON, never a blank screen. */
export default function UnknownComponent({ component }: { component: RichComponent }) {
  return (
    <Collapse
      size="small"
      style={{ marginTop: 8 }}
      items={[
        {
          key: 'json',
          label: (
            <Typography.Text type="secondary">
              {component.type} (unsupported component)
            </Typography.Text>
          ),
          children: (
            <pre
              style={{
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: 240,
                overflow: 'auto',
              }}
            >
              {JSON.stringify(component.data ?? {}, null, 2)}
            </pre>
          ),
        },
      ]}
    />
  );
}
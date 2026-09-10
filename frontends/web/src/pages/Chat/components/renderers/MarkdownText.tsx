import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from 'antd';
import { CheckOutlined, CopyOutlined } from '@ant-design/icons';
import { t } from '../../../../i18n';
import type { RichComponent } from '../../types';

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = String(children ?? '');

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div style={{ position: 'relative' }}>
      <Button
        size="small"
        icon={copied ? <CheckOutlined /> : <CopyOutlined />}
        onClick={copy}
        style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }}
      >
        {copied ? t('common', 'chat.copied', '已复制') : t('common', 'chat.copy', '复制')}
      </Button>
      <pre
        style={{
          margin: 0,
          background: '#f6f8fa',
          padding: 12,
          borderRadius: 6,
          overflow: 'auto',
        }}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}

/** RichTextComponent renderer: markdown via react-markdown + remark-gfm. */
export default function MarkdownText({ component }: { component: RichComponent }) {
  const data = component.data ?? {};
  const content = String(data.content ?? '');

  if (content === '') return null;

  if (!data.markdown) {
    return <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{content}</div>;
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code: ({ children, className }) =>
          className || String(children ?? '').includes('\n') ? (
            <CodeBlock>{children}</CodeBlock>
          ) : (
            <code style={{ background: '#f0f0f0', padding: '2px 5px', borderRadius: 4 }}>
              {children}
            </code>
          ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
import { useState } from 'react';
import { Button, Input } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { t } from '../../../i18n';

export interface ComposerProps {
  sending: boolean;
  placeholder?: string;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** Message input: Enter to send, Shift+Enter for a newline, stop while streaming. */
export default function Composer({ sending, placeholder, onSend, onStop }: ComposerProps) {
  const [value, setValue] = useState('');

  const submit = () => {
    const text = value.trim();
    if (!text || sending) return;
    setValue('');
    onSend(text);
  };

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: '12px 24px', borderTop: '1px solid #f0f0f0' }}>
      <Input.TextArea
        value={value}
        autoSize={{ minRows: 1, maxRows: 6 }}
        placeholder={placeholder ?? t('common', 'chat.inputPlaceholder', '输入问题，Enter 发送，Shift+Enter 换行')}
        style={{ flex: 1, resize: 'none' }}
        onChange={(e) => setValue(e.target.value)}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={sending}
      />
      {sending ? (
        <Button danger onClick={onStop}>
          {t('common', 'chat.stop', '停止')}
        </Button>
      ) : (
        <Button type="primary" icon={<SendOutlined />} disabled={!value.trim()} onClick={submit}>
          {t('common', 'chat.send', '发送')}
        </Button>
      )}
    </div>
  );
}
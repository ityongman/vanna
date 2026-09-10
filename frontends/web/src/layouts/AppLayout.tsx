import { Outlet, useLocation, useNavigate, useParams } from 'react-router';
import { GlobalOutlined, MessageOutlined } from '@ant-design/icons';
import { Button, Select, Tooltip } from 'antd';
import UserMenu from '../components/UserMenu';
import { useAuth } from '../lib/auth';
import { setLanguage, getLanguage, t, type Language } from '../i18n';

function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const { user } = useAuth();
  // /admin/* 管理路由不在业务段下，「返回聊天」回退到首个业务
  const businessId = params.businessId ?? user?.businesses?.[0];

  // 管理页等非聊天页显示“返回聊天”入口
  const showBackToChat = !location.pathname.endsWith('/chat');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header
        style={{
          height: 48,
          flex: 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          padding: '0 16px',
          borderBottom: '1px solid #f0f0f0',
          gap: 12,
          background: '#fff',
        }}
      >
        {showBackToChat && (
          <Tooltip title={t('menu', 'chat')}>
            <Button
              type="text"
              icon={<MessageOutlined />}
              onClick={() => navigate(`/${businessId}/chat`)}
            >
              {t('menu', 'chat')}
            </Button>
          </Tooltip>
        )}
        <Select
          value={getLanguage()}
          onChange={(val: Language) => setLanguage(val)}
          style={{ width: 110 }}
          variant="borderless"
          suffixIcon={<GlobalOutlined />}
          options={[
            { label: '简体中文', value: 'zh-CN' },
            { label: '繁體中文', value: 'zh-TW' },
            { label: 'English', value: 'en-US' },
          ]}
        />
        <UserMenu />
      </header>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <Outlet />
      </div>
    </div>
  );
}

export default AppLayout;

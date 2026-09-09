import { useNavigate } from 'react-router';
import { Avatar, Dropdown } from 'antd';
import { UserOutlined, LogoutOutlined, SettingOutlined, UploadOutlined, DatabaseOutlined } from '@ant-design/icons';
import { useAuth } from '../../lib/auth';
import { t } from '../../i18n';

function UserMenu() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const adminItems = user?.is_admin
    ? [
        { type: 'divider' as const },
        {
          key: 'manage-group',
          label: t('menu', 'manage'),
          icon: <SettingOutlined />,
          children: [
            {
              key: 'ddl-import',
              label: t('menu', 'ddl-import'),
              icon: <UploadOutlined />,
              // 管理页面与业务无关，挂在 /admin/* 下
              onClick: () => navigate('/admin/ddl-import'),
            },
            {
              key: 'schema',
              label: t('menu', 'schema'),
              icon: <DatabaseOutlined />,
              onClick: () => navigate('/admin/schema'),
            },
          ],
        },
      ]
    : [];

  return (
    <Dropdown
      menu={{
        items: [
          { key: 'email', label: user?.email || 'Anonymous', disabled: true },
          { type: 'divider' },
          { key: 'logout', label: t('menu', 'logout'), icon: <LogoutOutlined />, onClick: handleLogout },
          ...adminItems,
        ],
      }}
    >
      <Avatar icon={<UserOutlined />} style={{ cursor: 'pointer' }} />
    </Dropdown>
  );
}

export default UserMenu;

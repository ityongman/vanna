import { useNavigate } from 'react-router';
import { Avatar, Dropdown } from 'antd';
import { UserOutlined, LogoutOutlined } from '@ant-design/icons';
import { useAuth } from '../../lib/auth';

function UserMenu() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <Dropdown
      menu={{
        items: [
          { key: 'email', label: user?.email || 'Anonymous', disabled: true },
          { type: 'divider' },
          { key: 'logout', label: 'Logout', icon: <LogoutOutlined />, onClick: handleLogout },
        ],
      }}
    >
      <Avatar icon={<UserOutlined />} style={{ cursor: 'pointer' }} />
    </Dropdown>
  );
}

export default UserMenu;

import { Outlet, useNavigate, useParams, useLocation } from 'react-router';
import ProLayout from '@ant-design/pro-layout';
import {
  MessageOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import { Select } from 'antd';
import UserMenu from '../components/UserMenu';
import { t, setLanguage, getLanguage, type Language } from '../i18n';

const menuData = [
  { path: 'chat', i18nKey: 'chat', icon: <MessageOutlined /> },
];

function AppLayout() {
  const { businessId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <ProLayout
      title="Vanna"
      logo={false}
      route={{
        path: '/',
        routes: menuData.map(item => ({
          path: `/${businessId}/${item.path}`,
          name: t('menu', item.i18nKey),
          icon: item.icon,
        })),
      }}
      location={{ pathname: location.pathname }}
      menuItemRender={(item, dom) => (
        <div onClick={() => item.path && navigate(item.path)}>
          {dom}
        </div>
      )}
      actionsRender={() => [
        <Select
          key="lang"
          value={getLanguage()}
          onChange={(val: Language) => setLanguage(val)}
          style={{ width: 100 }}
          variant="borderless"
          suffixIcon={<GlobalOutlined />}
          options={[
            { label: '简体中文', value: 'zh-CN' },
            { label: '繁體中文', value: 'zh-TW' },
            { label: 'English', value: 'en-US' },
          ]}
        />,
      ]}
      avatarProps={{
        render: () => <UserMenu />,
      }}
      fixSiderbar
    >
      <Outlet />
    </ProLayout>
  );
}

export default AppLayout;

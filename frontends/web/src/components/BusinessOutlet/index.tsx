import { Outlet, useLocation, useNavigate, useParams } from 'react-router';
import { Select, Typography } from 'antd';
import { useAuth } from '../../lib/auth';

const { Text } = Typography;

// 这些管理页面自带业务选择器或不依赖 URL 业务上下文，无需显示顶部全局业务切换器
const NO_BUSINESS_SWITCHER_PAGES = new Set(['ddl-import', 'schema']);

function BusinessOutlet() {
  const { businessId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { user, setBusinessId } = useAuth();
  const businesses = user?.businesses ?? [];

  const handleChange = (newBusinessId: string) => {
    setBusinessId(newBusinessId);
    // Preserve the current page path, just swap the businessId prefix
    const segments = location.pathname.split('/');
    segments[1] = newBusinessId;
    navigate(segments.join('/'));
  };

  const pageSegments = location.pathname.split('/');
  const currentPage = pageSegments[pageSegments.length - 1];
  const showBusinessSwitcher =
    businesses.length > 1 && !NO_BUSINESS_SWITCHER_PAGES.has(currentPage);

  return (
    <div>
      {showBusinessSwitcher && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Text strong>Business:</Text>
          <Select
            value={businessId}
            onChange={handleChange}
            style={{ width: 240 }}
            options={businesses.map(b => ({ label: b, value: b }))}
          />
        </div>
      )}
      <Outlet />
    </div>
  );
}

export default BusinessOutlet;

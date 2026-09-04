import { Outlet, useNavigate, useParams } from 'react-router';
import { Select, Typography } from 'antd';
import { useAuth } from '../../lib/auth';

const { Text } = Typography;

function BusinessOutlet() {
  const { businessId } = useParams();
  const navigate = useNavigate();
  const { user, setBusinessId } = useAuth();
  const businesses = user?.businesses ?? [];

  const handleChange = (newBusinessId: string) => {
    setBusinessId(newBusinessId);
    // Preserve the current page path, just swap the businessId prefix
    const segments = location.pathname.split('/');
    segments[1] = newBusinessId;
    navigate(segments.join('/'));
  };

  return (
    <div>
      {businesses.length > 1 && (
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

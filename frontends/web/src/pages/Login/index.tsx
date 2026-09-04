import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Button, Card, Form, Select, Typography } from 'antd';
import { useAuth } from '../../lib/auth';

const { Title } = Typography;

function Login() {
  const navigate = useNavigate();
  const { user, refresh, setBusinessId } = useAuth();
  const [loading, setLoading] = useState(false);
  const businesses = user?.businesses ?? [];

  const onFinish = async (values: { email: string; businessId: string }) => {
    setLoading(true);
    // Set cookie for server-side auth
    document.cookie = `chatbot_email=${encodeURIComponent(values.email)}; path=/; max-age=31536000; SameSite=Lax`;
    setBusinessId(values.businessId || null);
    await refresh();
    navigate(`/${values.businessId}/chat`, { replace: true });
    setLoading(false);
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
      <Card style={{ width: 400 }}>
        <Title level={3} style={{ textAlign: 'center' }}>Vanna Login</Title>
        <p style={{ textAlign: 'center', color: '#666', marginBottom: 24 }}>
          Select account (admin accounts configured in config/app.json server.admin_emails)
        </p>
        <Form onFinish={onFinish} layout="vertical">
          <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
            <Select placeholder="Select email">
              <Select.Option value="admin@example.com">admin@example.com</Select.Option>
              <Select.Option value="user@example.com">user@example.com</Select.Option>
            </Select>
          </Form.Item>
          {businesses.length > 0 && (
            <Form.Item name="businessId" label="Business" rules={[{ required: true }]}>
              <Select placeholder="Select business">
                {businesses.map(b => (
                  <Select.Option key={b} value={b}>{b}</Select.Option>
                ))}
              </Select>
            </Form.Item>
          )}
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              Continue
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}

export default Login;

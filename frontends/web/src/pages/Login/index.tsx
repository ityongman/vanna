import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button, Card, Form, Input, Typography } from 'antd';
import { useAuth } from '../../lib/auth';
import { api } from '../../lib/api';

const { Title } = Typography;

function Login() {
  const navigate = useNavigate();
  const { refresh, setBusinessId, businessId } = useAuth();
  const [loading, setLoading] = useState(false);
  const [businesses, setBusinesses] = useState<string[]>([]);

  // Fetch businesses independently of auth state
  useEffect(() => {
    api.me().then(me => {
      setBusinesses(me.businesses || []);
    }).catch(() => {});
  }, []);

  const onFinish = async (values: { email: string }) => {
    setLoading(true);
    // Set cookie for server-side auth
    document.cookie = `chatbot_email=${encodeURIComponent(values.email)}; path=/; max-age=31536000; SameSite=Lax`;
    // 优先使用 localStorage 记住的上次业务，否则默认第一个业务
    const bizId = (businessId && businesses.includes(businessId) ? businessId : businesses[0]) || '';
    setBusinessId(bizId || null);
    await refresh();
    navigate(bizId ? `/${bizId}/chat` : '/', { replace: true });
    setLoading(false);
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
      <Card style={{ width: 400 }}>
        <Title level={3} style={{ textAlign: 'center' }}>Vanna Login</Title>
        <p style={{ textAlign: 'center', color: '#666', marginBottom: 24 }}>
          Enter your email to continue
        </p>
        <Form onFinish={onFinish} layout="vertical">
          <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
            <Input placeholder="Enter your email" />
          </Form.Item>
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

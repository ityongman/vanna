import { useParams } from 'react-router';
import { Typography } from 'antd';

function Train() {
  const { businessId } = useParams();
  return <Typography.Title level={4}>Train — {businessId}</Typography.Title>;
}

export default Train;

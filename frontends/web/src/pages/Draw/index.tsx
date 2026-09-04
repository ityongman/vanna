import { useParams } from 'react-router';
import { Typography } from 'antd';

function Draw() {
  const { businessId } = useParams();
  return <Typography.Title level={4}>Draw — {businessId}</Typography.Title>;
}

export default Draw;

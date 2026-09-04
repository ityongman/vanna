import { useParams } from 'react-router';
import { Typography } from 'antd';

function Manage() {
  const { businessId } = useParams();
  return <Typography.Title level={4}>Manage — {businessId}</Typography.Title>;
}

export default Manage;

import React from 'react';
import ReactDOM from 'react-dom/client';
// React 19 下 antd v5 静态方法（Modal.confirm/message 等）依赖 ReactDOM.render，
// 需要官方补丁使 Modal.confirm / message / notification 正常工作
import '@ant-design/v5-patch-for-react-19';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root')!);

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

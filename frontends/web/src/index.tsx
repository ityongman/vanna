import ReactDOM from 'react-dom/client';
// React 19 下 antd v5 静态方法（Modal.confirm/message 等）依赖 ReactDOM.render，
// 需要官方补丁使 Modal.confirm / message / notification 正常工作
import '@ant-design/v5-patch-for-react-19';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root')!);

// 注意：不使用 React.StrictMode —— 开发模式下它会双挂载组件导致所有
// effect 执行两遍（SSE/列表请求成对发出），聊天流式场景下代价大于收益。
root.render(<App />);

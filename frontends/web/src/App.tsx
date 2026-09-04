import { RouterProvider } from 'react-router';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { router } from './router';

const antdLocaleMap: Record<string, typeof zhCN> = {
  'zh-CN': zhCN,
};

function App() {
  // TODO: bind to i18n language when i18n is implemented
  const antdLocale = antdLocaleMap['zh-CN'] || zhCN;

  return (
    <ConfigProvider locale={antdLocale}>
      <RouterProvider router={router} />
    </ConfigProvider>
  );
}

export default App;

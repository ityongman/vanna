import { Suspense, lazy } from 'react';
import { createBrowserRouter, Navigate, Outlet } from 'react-router';
import { AuthProvider, AdminGuard } from './lib/auth';
import AuthGuard from './layouts/AuthGuard';
import AppLayout from './layouts/AppLayout';
import BusinessOutlet from './components/BusinessOutlet';
import GlobalLoading from './components/GlobalLoading';

// 页面级懒加载：antd 的 Table/Form/Upload/Steps 等重组件仅由少数页面使用，
// 按路由拆分可避免首屏加载全部页面代码。
const Login = lazy(() => import('./pages/Login'));
const Chat = lazy(() => import('./pages/Chat'));
const Draw = lazy(() => import('./pages/Draw'));
const Manage = lazy(() => import('./pages/Manage'));
const Train = lazy(() => import('./pages/Train'));
const DdlImport = lazy(() => import('./pages/DdlImport'));
const Schema = lazy(() => import('./pages/Schema'));
const NotFound = lazy(() => import('./pages/NotFound'));

function RootLayout() {
  return (
    <AuthProvider>
      <Suspense fallback={<GlobalLoading />}>
        <Outlet />
      </Suspense>
    </AuthProvider>
  );
}

function AdminRoutes() {
  return (
    <AdminGuard>
      <Outlet />
    </AdminGuard>
  );
}

export const router = createBrowserRouter(
  [
    {
      element: <RootLayout />,
      children: [
        {
          path: '/login',
          element: <Login />,
        },
        {
          path: '/',
          element: <AuthGuard />,
          children: [
            {
              index: true,
              element: <Navigate to="/equipment_decay/chat" replace />,
            },
            {
              path: ':businessId',
              element: <AppLayout />,
              children: [
                {
                  element: <BusinessOutlet />,
                  children: [
                    { index: true, element: <Navigate to="chat" replace /> },
                    { path: 'chat', element: <Chat /> },
                    { path: 'draw', element: <Draw /> },
                    { path: 'manage', element: <Manage /> },
                    { path: 'train', element: <Train /> },
                  ],
                },
              ],
            },
            {
              // 管理页面与具体业务无关（导入目标由 CSV db_name 决定），
              // 放在业务路由之外，避免 URL 携带业务段造成误解。
              path: 'admin',
              element: <AppLayout />,
              children: [
                {
                  element: <AdminRoutes />,
                  children: [
                    { path: 'ddl-import', element: <DdlImport /> },
                    { path: 'schema', element: <Schema /> },
                  ],
                },
              ],
            },
          ],
        },
        {
          path: '*',
          element: <NotFound />,
        },
      ],
    },
  ],
  { basename: '/app' }
);

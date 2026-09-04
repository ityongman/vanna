import { createBrowserRouter, Navigate, Outlet } from 'react-router';
import { AuthProvider, AdminGuard } from './lib/auth';
import AuthGuard from './layouts/AuthGuard';
import AppLayout from './layouts/AppLayout';
import BusinessOutlet from './components/BusinessOutlet';
import Login from './pages/Login';
import Chat from './pages/Chat';
import Draw from './pages/Draw';
import Manage from './pages/Manage';
import Train from './pages/Train';
import DdlImport from './pages/DdlImport';
import Schema from './pages/Schema';
import NotFound from './pages/NotFound';

function RootLayout() {
  return (
    <AuthProvider>
      <Outlet />
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

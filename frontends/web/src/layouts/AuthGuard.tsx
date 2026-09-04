import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuth } from '../lib/auth';
import GlobalLoading from '../components/GlobalLoading';

function AuthGuard() {
  const location = useLocation();
  const { user, loading } = useAuth();

  if (loading) return <GlobalLoading />;
  if (!user?.email) return <Navigate to="/login" state={{ from: location }} replace />;

  return <Outlet />;
}

export default AuthGuard;

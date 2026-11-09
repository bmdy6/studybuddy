import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { Result, Button } from 'antd';
import { useAuth } from '@/features/auth/useAuth';

interface Props {
  children: ReactNode;
  /** 限制只允许哪个角色访问，不传则所有登录用户可访问 */
  role?: 'parent' | 'student';
}

/**
 * 路由守卫：未登录重定向到 /login，记住来源路径。
 * 若指定 role，不匹配则显示 403 页面。
 */
export default function ProtectedRoute({ children, role }: Props) {
  const { isAuthenticated, role: userRole } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  if (role && userRole !== role) {
    return (
      <Result
        status="403"
        title="无权访问"
        subTitle="你没有权限查看此页面"
        extra={
          <Button type="primary" onClick={() => window.history.back()}>
            返回
          </Button>
        }
      />
    );
  }

  return <>{children}</>;
}

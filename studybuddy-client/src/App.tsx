import { HashRouter } from 'react-router-dom';
import { App as AntdApp } from 'antd';
import AppRoutes from '@/app/router';

/**
 * 应用根组件：Provider 壳 + 路由。
 * 路由聚合在 @/app/router，各 feature 后续导出自己的 routes.tsx。
 */
export default function App() {
  return (
    <AntdApp>
      <HashRouter>
        <AppRoutes />
      </HashRouter>
    </AntdApp>
  );
}

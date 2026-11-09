import { Navigate } from 'react-router-dom';

/**
 * 角色重定向：登录后统一跳 /chat（agent 对话首页）。
 * P2 agent 化后，首页改为 agent 对话页，parent/student 都从对话进入。
 */
export default function RoleRedirect() {
  return <Navigate to="/chat" replace />;
}

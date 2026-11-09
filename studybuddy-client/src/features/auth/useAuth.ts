import { useCallback } from 'react';
import { App } from 'antd';
import { useAuthStore } from '@/features/auth/store';
import { authApi } from '@/features/auth/api';
import { ROLES, type Role } from '@/shared/constants';
import type { LoginRequest, LoginResponse, RegisterRequest } from '@/types';

/**
 * 登录 / 登出封装。
 * 用 antd App.useApp() 拿 message 实例，避免静态方法在 ConfigProvider 外失效。
 *
 * ★ 阶段一角色映射：后端仍返回 'teacher'，前端统一映射成 'parent'。
 *   阶段二后端迁移完成后，后端直接返回 'parent'，此映射变成 no-op，可删除。
 */
export function useAuth() {
  const message = App.useApp().message;
  const {
    token,
    role,
    displayName,
    avatar,
    userId,
    children,
    activeChildId,
    authVersion,
    recentAccounts,
    login,
    logout,
    switchAccount,
    forgetAccount,
    setActiveChild,
    updateProfile,
    mode,
    setMode,
  } = useAuthStore();

  const saveLoginResponse = useCallback(
    (res: LoginResponse, username: string) => {
      const mappedRole: Role = res.role === 'teacher' ? ROLES.PARENT : (res.role as Role);
      const kids = mappedRole === ROLES.PARENT ? (res.children ?? []) : [];
      login(res.access_token, mappedRole, res.display_name, res.avatar, res.user_id, kids, username, res.mode);
    },
    [login],
  );

  const doLogin = useCallback(
    async (req: LoginRequest): Promise<boolean> => {
      try {
        const res = await authApi.login(req);
        saveLoginResponse(res, req.username);
        message.success(`欢迎回来，${res.display_name}`);
        return true;
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '登录失败，请检查用户名密码';
        message.error(msg);
        return false;
      }
    },
    [message, saveLoginResponse],
  );

  const doRegister = useCallback(
    async (req: RegisterRequest): Promise<boolean> => {
      try {
        const res = await authApi.register(req);
        saveLoginResponse(res, req.username.trim());
        message.success('注册成功');
        return true;
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '注册失败，请稍后重试';
        message.error(msg);
        return false;
      }
    },
    [message, saveLoginResponse],
  );

  const doLogout = useCallback(() => {
    logout();
    message.info('已退出登录');
    window.location.hash = '#/login';
  }, [logout, message]);

  return {
    token,
    role,
    displayName,
    avatar,
    userId,
    children,
    activeChildId,
    authVersion,
    recentAccounts,
    isAuthenticated: !!token,
    login: doLogin,
    register: doRegister,
    logout: doLogout,
    switchAccount,
    forgetAccount,
    setActiveChild,
    updateProfile,
    mode,
    setMode,
  };
}

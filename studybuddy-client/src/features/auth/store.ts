import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { ROLES, type Role } from '@/shared/constants';
import type { ChildInfo } from '@/types';

export interface RecentAccount {
  id: string;
  username: string;
  token: string;
  role: Role;
  displayName: string;
  avatar: string | null;
  userId: number | null;
  children: ChildInfo[];
  activeChildId: number | null;
  lastLoginAt: string;
}

interface AuthState {
  token: string | null;
  role: Role | null;
  displayName: string | null;
  avatar: string | null;
  userId: number | null;
  children: ChildInfo[];
  activeChildId: number | null;
  mode: 'study' | 'hobby';
  authVersion: number;
  recentAccounts: RecentAccount[];
  login: (
    token: string,
    role: Role,
    displayName: string,
    avatar?: string | null,
    userId?: number,
    children?: ChildInfo[],
    username?: string,
    mode?: 'study' | 'hobby',
  ) => void;
  logout: () => void;
  switchAccount: (id: string) => boolean;
  forgetAccount: (id: string) => void;
  setActiveChild: (id: number) => void;
  /** 个人中心改完资料后同步本地（UX P0-1） */
  updateProfile: (displayName: string, avatar: string | null) => void;
  /** 切换模式（study=学习 / hobby=兴趣爱好），同账号全量复用 */
  setMode: (mode: 'study' | 'hobby') => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      role: null,
      displayName: null,
      avatar: null,
      userId: null,
      children: [],
      activeChildId: null,
      mode: 'study' as const,
      authVersion: 0,
      recentAccounts: [],
      login: (token, role, displayName, avatar = null, userId, children = [], username, mode = 'study') =>
        set((state) => {
          const normalizedUserId = userId ?? null;
          const activeChildId = children[0]?.id ?? null;
          const accountId = normalizedUserId !== null ? String(normalizedUserId) : username || displayName;
          const accountUsername = username || displayName;
          const snapshot: RecentAccount = {
            id: accountId,
            username: accountUsername,
            token,
            role,
            displayName,
            avatar,
            userId: normalizedUserId,
            children,
            activeChildId,
            lastLoginAt: new Date().toISOString(),
          };
          const recentAccounts = [
            snapshot,
            ...state.recentAccounts.filter((item) => item.id !== accountId),
          ].slice(0, 5);
          return {
            token,
            role,
            displayName,
            avatar,
            userId: normalizedUserId,
            children,
            // 单孩子自动锁定，无需切换器；多孩子默认选第一个
            activeChildId,
            mode,
            authVersion: state.authVersion + 1,
            recentAccounts,
          };
        }),
      logout: () =>
        set((state) => ({
          token: null,
          role: null,
          displayName: null,
          avatar: null,
          userId: null,
          children: [],
          activeChildId: null,
          mode: 'study' as const,
          authVersion: state.authVersion + 1,
        })),
      switchAccount: (id) => {
        const account = useAuthStore.getState().recentAccounts.find((item) => item.id === id);
        if (!account) return false;
        set((state) => ({
          token: account.token,
          role: account.role,
          displayName: account.displayName,
          avatar: account.avatar,
          userId: account.userId,
          children: account.children,
          activeChildId: account.activeChildId,
          mode: 'study' as const,
          authVersion: state.authVersion + 1,
          recentAccounts: [
            { ...account, lastLoginAt: new Date().toISOString() },
            ...useAuthStore.getState().recentAccounts.filter((item) => item.id !== id),
          ],
        }));
        return true;
      },
      forgetAccount: (id) =>
        set((state) => ({ recentAccounts: state.recentAccounts.filter((item) => item.id !== id) })),
      setActiveChild: (id) => set((state) => ({ activeChildId: id, authVersion: state.authVersion + 1 })),
      updateProfile: (displayName, avatar) => set({ displayName, avatar }),
      setMode: (mode) => set({ mode }),
    }),
    { name: 'studybuddy-auth' },
  ),
);

/** 取当前查看的学生 id：parent→activeChildId，student→自己 */
export function getActiveStudentId(state: AuthState): number | null {
  if (state.role === ROLES.PARENT) return state.activeChildId;
  if (state.role === ROLES.STUDENT) return state.userId;
  return null;
}

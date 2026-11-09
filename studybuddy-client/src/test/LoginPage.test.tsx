import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import LoginPage from '@/features/auth/pages/LoginPage';
import { useAuthStore } from '@/features/auth/store';

const { mockLogin, mockRegister, mockMessageError } = vi.hoisted(() => ({
  mockLogin: vi.fn(),
  mockRegister: vi.fn(),
  mockMessageError: vi.fn(),
}));

vi.mock('@/features/auth/api', () => ({
  authApi: {
    login: mockLogin,
    register: mockRegister,
  },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: {
      success: vi.fn(),
      error: mockMessageError,
      info: vi.fn(),
      warning: vi.fn(),
    },
  });
  return { ...actual, App: AppMock };
});

function TargetPage() {
  const location = useLocation();
  return <div>target:{`${location.pathname}${location.search}`}</div>;
}

function renderLogin(from = '/materials?source=wechat') {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state: { from } }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/materials" element={<TargetPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('LoginPage registration', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLogin.mockReset();
    mockRegister.mockReset();
    mockMessageError.mockReset();
    useAuthStore.setState({
      token: null,
      role: null,
      displayName: null,
      avatar: null,
      userId: null,
      children: [],
      activeChildId: null,
      recentAccounts: [],
      authVersion: 0,
    });
  });

  it('注册成功后保存登录态并返回微信来源页面', async () => {
    mockRegister.mockResolvedValue({
      access_token: 'registered-token',
      token_type: 'bearer',
      expires_in: 30 * 24 * 3600,
      user_id: 88,
      role: 'student',
      display_name: '微信学生',
      avatar: null,
      children: [],
    });
    renderLogin();

    fireEvent.click(screen.getByRole('button', { name: '注册账号' }));
    fireEvent.change(screen.getByPlaceholderText('用户名'), { target: { value: '  微信学生  ' } });
    fireEvent.change(screen.getByPlaceholderText('密码（至少 6 位）'), { target: { value: 'student123' } });
    fireEvent.change(screen.getByPlaceholderText('再次输入密码'), { target: { value: 'student123' } });
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }));

    expect(await screen.findByText('target:/materials?source=wechat')).toBeInTheDocument();
    expect(mockRegister).toHaveBeenCalledWith({ username: '  微信学生  ', password: 'student123' });
    expect(useAuthStore.getState().token).toBe('registered-token');
    expect(useAuthStore.getState().recentAccounts[0]?.username).toBe('微信学生');
    await waitFor(() => expect(localStorage.getItem('studybuddy-auth')).toContain('registered-token'));
  });

  it('登录页注册入口使用清晰的行动按钮样式', () => {
    renderLogin();

    const registerButton = screen.getByRole('button', { name: '注册账号' });

    expect(registerButton).toHaveClass('sb-login-switch-action');
  });

  it('两次密码不一致时不发送注册请求', async () => {
    renderLogin('/chat');

    fireEvent.click(screen.getByRole('button', { name: '注册账号' }));
    fireEvent.change(screen.getByPlaceholderText('用户名'), { target: { value: 'new-student' } });
    fireEvent.change(screen.getByPlaceholderText('密码（至少 6 位）'), { target: { value: 'student123' } });
    fireEvent.change(screen.getByPlaceholderText('再次输入密码'), { target: { value: 'student456' } });
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }));

    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it('重复用户名显示后端错误', async () => {
    mockRegister.mockRejectedValue({ response: { data: { detail: '用户名已被使用' } } });
    renderLogin('/chat');

    fireEvent.click(screen.getByRole('button', { name: '注册账号' }));
    fireEvent.change(screen.getByPlaceholderText('用户名'), { target: { value: 'student' } });
    fireEvent.change(screen.getByPlaceholderText('密码（至少 6 位）'), { target: { value: 'student123' } });
    fireEvent.change(screen.getByPlaceholderText('再次输入密码'), { target: { value: 'student123' } });
    fireEvent.click(screen.getByRole('button', { name: '注册并进入' }));

    await waitFor(() => expect(mockMessageError).toHaveBeenCalledWith('用户名已被使用'));
  });
});

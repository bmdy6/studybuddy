import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from 'antd';
import { forwardRef, type ReactNode } from 'react';
import AccountPage from '@/features/family/pages/AccountPage';
import { wechatApi, type WechatBindSession } from '@/features/wechat/api';
import { familyGoalApi } from '@/features/family_goal/api';
import type { FamilyTodayTask } from '@/types';

vi.mock('qrcode.react', () => ({
  QRCodeCanvas: forwardRef<HTMLCanvasElement, { value: string }>(function MockQrCodeCanvas(
    { value },
    ref,
  ) {
    return <canvas ref={ref} data-qr-value={value} />;
  }),
}));

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    displayName: '测试学生',
    avatar: null,
    role: 'student',
    userId: 2,
    updateProfile: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock('@/features/family_goal/api', () => ({
  familyGoalApi: { todayTasks: vi.fn() },
}));

vi.mock('@/features/auth/api', () => ({
  authApi: {
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
  },
}));

vi.mock('@/features/wechat/api', () => ({
  wechatApi: {
    getAccount: vi.fn(),
    createBindSession: vi.fn(),
    getBindSession: vi.fn(),
    unbind: vi.fn(),
  },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

const mockedWechatApi = vi.mocked(wechatApi);
const mockedFamilyGoalApi = vi.mocked(familyGoalApi);

function renderAccountPage() {
  return render(
    <App>
      <MemoryRouter>
        <AccountPage />
      </MemoryRouter>
    </App>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  mockedFamilyGoalApi.todayTasks.mockResolvedValue([]);
  mockedWechatApi.getAccount.mockResolvedValue({ bound: false });
  mockedWechatApi.createBindSession.mockImplementation(async () => ({
    id: 42,
    bind_code: 'W711966',
    qr_value: 'https://example.test/ilink-authorization-1',
    status: 'pending',
    expires_at: new Date(Date.now() + 180999).toISOString().replace('Z', ''),
    bound_at: null,
  }));
  mockedWechatApi.getBindSession.mockResolvedValue({
    id: 42,
    bind_code: 'W711966',
    qr_value: 'https://example.test/ilink-authorization-1',
    status: 'pending',
    expires_at: new Date(Date.now() + 180000).toISOString().replace('Z', ''),
    bound_at: null,
  });
  mockedWechatApi.unbind.mockResolvedValue(undefined);
  Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
    configurable: true,
    value: vi.fn(() => 'data:image/png;base64,cXJjb2Rl'),
  });
});

describe('AccountPage mobile personal center', () => {
  it('groups primary actions and keeps forms out of the default view', async () => {
    renderAccountPage();

    expect(await screen.findByText('学习与连接')).toBeInTheDocument();
    expect(screen.getByText('账户与支持')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /测试学生.*学生.*编辑个人资料/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /微信学习助手.*未绑定/ })).toBeInTheDocument();
    expect(screen.queryByLabelText('显示名称')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('当前密码')).not.toBeInTheDocument();
  });

  it('clears password fields after the security drawer closes', async () => {
    const user = userEvent.setup();
    renderAccountPage();

    await user.click(screen.getByRole('button', { name: /账号安全.*修改登录密码/ }));
    let dialog = screen.getByRole('dialog', { name: '账号安全' });
    await user.type(within(dialog).getByLabelText('当前密码'), 'old-secret');
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '账号安全' })).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /账号安全.*修改登录密码/ }));
    dialog = screen.getByRole('dialog', { name: '账号安全' });
    expect(within(dialog).getByLabelText('当前密码')).toHaveValue('');
  });

  it('opens profile, security, and wechat tasks in bottom drawers', async () => {
    const user = userEvent.setup();
    renderAccountPage();

    await user.click(await screen.findByRole('button', { name: /测试学生.*编辑个人资料/ }));
    let dialog = screen.getByRole('dialog', { name: '编辑个人资料' });
    expect(within(dialog).getByLabelText('显示名称')).toHaveValue('测试学生');
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '编辑个人资料' })).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /账号安全.*修改登录密码/ }));
    dialog = screen.getByRole('dialog', { name: '账号安全' });
    expect(within(dialog).getByLabelText('当前密码')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '账号安全' })).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /微信学习助手.*未绑定/ }));
    dialog = screen.getByRole('dialog', { name: '微信学习助手' });
    expect(within(dialog).getByRole('button', { name: /绑定微信学习助手/ })).toBeInTheDocument();
  });
});

describe('AccountPage wechat binding', () => {

  it('shows the copy, save, scan, and send-code instructions', async () => {
    renderAccountPage();

    await userEvent.click(await screen.findByRole('button', { name: /微信学习助手.*未绑定/ }));
    expect(screen.getByText('在微信继续学习和接收动态')).toBeInTheDocument();
    expect(screen.queryByText(/快速进入学习工具/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /绑定微信学习助手/ }));

    expect(await screen.findByText('W711966')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复制绑定码' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '微信学习助手二维码' })).toHaveAttribute(
      'data-qr-value',
      'https://example.test/ilink-authorization-1',
    );
    expect(screen.getAllByText('先复制绑定码')).toHaveLength(2);
    expect(screen.getByText('长按二维码，保存到手机')).toBeInTheDocument();
    expect(screen.getByText('打开微信“扫一扫”，从相册选择二维码')).toBeInTheDocument();
    expect(
      screen.getByText('进入“微信ClawBot AI”对话，粘贴并发送绑定码'),
    ).toBeInTheDocument();
    expect(screen.getByText('03:00')).toBeInTheDocument();
    expect(screen.getByText(/不会读取你的微信聊天记录/)).toBeInTheDocument();
    expect(screen.queryByText(/公众号|学明白了/)).not.toBeInTheDocument();
  });

  it('restores a pending bind session after the page reloads', async () => {
    window.sessionStorage.setItem('studybuddy:wechat-bind-session:2', '42');

    renderAccountPage();
    await userEvent.click(await screen.findByRole('button', { name: /微信学习助手.*未绑定/ }));

    await waitFor(() => expect(mockedWechatApi.getBindSession).toHaveBeenCalledWith(42));
    expect(mockedWechatApi.createBindSession).not.toHaveBeenCalled();
    expect(await screen.findByText('W711966')).toBeInTheDocument();
  });

  it('refreshes the binding code from the restored session state', async () => {
    vi.useFakeTimers();
    mockedWechatApi.getBindSession.mockResolvedValue({
      id: 42,
      bind_code: 'W722077',
      qr_value: 'https://example.test/ilink-authorization-2',
      status: 'pending',
      expires_at: new Date(Date.now() + 180000).toISOString(),
      bound_at: null,
    });
    try {
      renderAccountPage();
      await act(async () => Promise.resolve());
      fireEvent.click(screen.getByRole('button', { name: /微信学习助手/ }));
      fireEvent.click(screen.getByRole('button', { name: /绑定微信学习助手/ }));
      await act(async () => Promise.resolve());

      expect(screen.getByText('W711966')).toBeInTheDocument();
      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(screen.getByText('W722077')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries after a transient bind-session poll failure', async () => {
    vi.useFakeTimers();
    mockedWechatApi.getBindSession
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue({
        id: 42,
        bind_code: 'W711966',
        qr_value: 'https://example.test/ilink-authorization-1',
        status: 'bound',
        expires_at: new Date(Date.now() + 180000).toISOString(),
        bound_at: new Date().toISOString(),
      });
    mockedWechatApi.getAccount
      .mockResolvedValueOnce({ bound: false })
      .mockResolvedValue({
        bound: true,
        openid_masked: 'openid***0001',
        bound_at: null,
      });
    try {
      renderAccountPage();
      await act(async () => Promise.resolve());
      fireEvent.click(screen.getByRole('button', { name: /微信学习助手/ }));
      fireEvent.click(screen.getByRole('button', { name: /绑定微信学习助手/ }));
      await act(async () => Promise.resolve());

      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(1);
      await act(async () => vi.advanceTimersByTimeAsync(3000));

      expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(2);
      expect(screen.getByText('已绑定微信学习助手')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not overlap bind-session poll requests', async () => {
    vi.useFakeTimers();
    let resolvePoll: ((value: WechatBindSession) => void) | undefined;
    mockedWechatApi.getBindSession.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePoll = resolve;
        }),
    );
    try {
      renderAccountPage();
      await act(async () => Promise.resolve());
      fireEvent.click(screen.getByRole('button', { name: /微信学习助手/ }));
      fireEvent.click(screen.getByRole('button', { name: /绑定微信学习助手/ }));
      await act(async () => Promise.resolve());

      await act(async () => vi.advanceTimersByTimeAsync(9000));
      expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolvePoll?.({
          id: 42,
          bind_code: 'W711966',
          qr_value: 'https://example.test/ilink-authorization-1',
          status: 'pending',
          expires_at: new Date(Date.now() + 180000).toISOString(),
          bound_at: null,
        });
        await Promise.resolve();
      });
      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(2);
      await act(async () => {
        resolvePoll?.({
          id: 42,
          bind_code: 'W711966',
          qr_value: 'https://example.test/ilink-authorization-1',
          status: 'pending',
          expires_at: new Date(Date.now() + 180000).toISOString(),
          bound_at: null,
        });
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('marks the binding code expired when the server expiry is reached', async () => {
    mockedWechatApi.createBindSession.mockResolvedValue({
      id: 42,
      bind_code: 'W711966',
      qr_value: 'https://example.test/ilink-authorization-1',
      status: 'pending',
      expires_at: new Date(Date.now() + 100).toISOString(),
      bound_at: null,
    });
    renderAccountPage();

    await userEvent.click(await screen.findByRole('button', { name: /微信学习助手.*未绑定/ }));
    await userEvent.click(screen.getByRole('button', { name: /绑定微信学习助手/ }));

    expect(
      await screen.findByText('二维码或绑定码已失效', {}, { timeout: 2000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重新生成二维码和绑定码/ })).toBeInTheDocument();
  });

  it('keeps a bound session out of the expired state while account status is syncing', async () => {
    vi.useFakeTimers();
    mockedWechatApi.getAccount
      .mockResolvedValueOnce({ bound: false })
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue({ bound: true, openid_masked: 'openid***0001', bound_at: null });
    mockedWechatApi.getBindSession.mockResolvedValue({
      id: 42,
      bind_code: 'W711966',
      qr_value: 'https://example.test/ilink-authorization-1',
      status: 'bound',
      expires_at: new Date(Date.now() + 180000).toISOString(),
      bound_at: new Date().toISOString(),
    });
    try {
      renderAccountPage();
      await act(async () => Promise.resolve());
      fireEvent.click(screen.getByRole('button', { name: /微信学习助手/ }));
      fireEvent.click(screen.getByRole('button', { name: /绑定微信学习助手/ }));
      await act(async () => Promise.resolve());

      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(screen.getByText('微信学习助手已绑定')).toBeInTheDocument();
      expect(screen.queryByText('二维码或绑定码已失效')).not.toBeInTheDocument();

      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(screen.getByText('已绑定微信学习助手')).toBeInTheDocument();
      const accountCalls = mockedWechatApi.getAccount.mock.calls.length;
      await act(async () => vi.advanceTimersByTimeAsync(6000));
      expect(mockedWechatApi.getAccount).toHaveBeenCalledTimes(accountCalls);
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows bound account and can unbind', async () => {
    mockedWechatApi.getAccount.mockResolvedValue({ bound: true, openid_masked: 'openid***0001', bound_at: null });
    renderAccountPage();

    await userEvent.click(await screen.findByRole('button', { name: /微信学习助手.*已绑定/ }));
    expect(screen.getByText('openid***0001')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '解除绑定' }));

    await waitFor(() => expect(mockedWechatApi.unbind).toHaveBeenCalled());
  });

  it('显示家庭陪伴入口', async () => {
    mockedWechatApi.getAccount.mockResolvedValue({ bound: true, openid_masked: 'openid***0001', bound_at: null });
    renderAccountPage();

    expect(await screen.findByText('家庭陪伴')).toBeInTheDocument();
  });
});

// 有待完成家庭任务时，「我的」页这行要能看出今天有事做（手机端列表行没有徽标，只能靠 status 插槽）
describe('家庭任务入口提醒', () => {
  it('有待完成家庭任务时「家庭任务」行显示件数', async () => {
    mockedFamilyGoalApi.todayTasks.mockResolvedValue([
      { status: 'pending' },
      { status: 'submitted' },
      { status: 'rejected' },
    ] as unknown as FamilyTodayTask[]);
    renderAccountPage();

    expect(await screen.findByRole('button', { name: /家庭任务.*2 件待完成/ })).toBeInTheDocument();
  });

  it('没有待完成家庭任务时不显示件数', async () => {
    mockedFamilyGoalApi.todayTasks.mockResolvedValue([
      { status: 'submitted' },
      { status: 'approved' },
    ] as unknown as FamilyTodayTask[]);
    renderAccountPage();

    expect(await screen.findByRole('button', { name: /家庭任务/ })).toBeInTheDocument();
    expect(screen.queryByText(/件待完成/)).not.toBeInTheDocument();
  });
});

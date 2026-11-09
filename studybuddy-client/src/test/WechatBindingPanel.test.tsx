import { createRef, forwardRef, StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WechatBindingPanel, {
  type WechatBindingPanelHandle,
} from '@/features/wechat/components/WechatBindingPanel';
import { wechatApi } from '@/features/wechat/api';

vi.mock('qrcode.react', () => ({
  QRCodeCanvas: forwardRef<HTMLCanvasElement, { value: string }>(function MockQrCodeCanvas(
    { value },
    ref,
  ) {
    return <canvas ref={ref} data-qr-value={value} />;
  }),
}));

vi.mock('@/features/wechat/api', () => ({
  wechatApi: {
    createBindSession: vi.fn(),
    getBindSession: vi.fn(),
  },
}));

const mockedWechatApi = vi.mocked(wechatApi);
const pendingSession = {
  id: 42,
  bind_code: 'W711966',
  qr_value: 'https://example.test/ilink-authorization',
  status: 'pending' as const,
  expires_at: new Date(Date.now() + 180000).toISOString(),
  bound_at: null,
};

describe('WechatBindingPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
    mockedWechatApi.createBindSession.mockResolvedValue(pendingSession);
    mockedWechatApi.getBindSession.mockResolvedValue(pendingSession);
    Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
      configurable: true,
      value: vi.fn(() => 'data:image/png;base64,cXJjb2Rl'),
    });
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('auto starts and stores the reusable shared bot binding session', async () => {
    render(<WechatBindingPanel userId={2} autoStart />);

    expect(await screen.findByText('W711966')).toBeInTheDocument();
    expect(window.sessionStorage.getItem('studybuddy:wechat-bind-session:2')).toBe('42');
  });

  it('shows the copy code, savable QR, and four steps in the real mobile order', async () => {
    render(<WechatBindingPanel userId={2} autoStart />);

    const bindCode = await screen.findByText('W711966');
    expect(screen.getByRole('button', { name: '复制绑定码' })).toBeInTheDocument();
    const qr = screen.getByRole('img', { name: '微信学习助手二维码' });
    expect(qr).toHaveAttribute('src', 'data:image/png;base64,cXJjb2Rl');
    expect(qr).toHaveAttribute('data-qr-value', pendingSession.qr_value);
    expect(bindCode.compareDocumentPosition(qr) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByText('先复制绑定码')).toHaveLength(2);
    expect(screen.getByText('长按二维码，保存到手机')).toBeInTheDocument();
    expect(screen.getByText('打开微信“扫一扫”，从相册选择二维码')).toBeInTheDocument();
    expect(
      screen.getByText('进入“微信ClawBot AI”对话，粘贴并发送绑定码'),
    ).toBeInTheDocument();
  });

  it('confirms when the binding code is copied', async () => {
    render(<WechatBindingPanel userId={2} autoStart />);

    fireEvent.click(await screen.findByRole('button', { name: '复制绑定码' }));

    expect(await screen.findByText('已复制')).toBeInTheDocument();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('W711966');
  });

  it('reuses one session request when StrictMode mounts the onboarding twice', async () => {
    render(
      <StrictMode>
        <WechatBindingPanel userId={2} autoStart />
      </StrictMode>,
    );

    await screen.findByText('W711966');
    expect(mockedWechatApi.createBindSession).toHaveBeenCalledTimes(1);
  });

  it('restores the current session instead of generating another binding code', async () => {
    window.sessionStorage.setItem('studybuddy:wechat-bind-session:2', '42');

    render(
      <StrictMode>
        <WechatBindingPanel userId={2} />
      </StrictMode>,
    );

    await waitFor(() => expect(mockedWechatApi.getBindSession).toHaveBeenCalledWith(42));
    expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(1);
    expect(mockedWechatApi.createBindSession).not.toHaveBeenCalled();
  });

  it('clears both recovery and reminder markers after binding succeeds', async () => {
    window.sessionStorage.setItem('studybuddy:wechat-bind-session:2', '42');
    window.localStorage.setItem('studybuddy:wechat-bind-snoozed-on:2', '2026-07-14');
    mockedWechatApi.getBindSession.mockResolvedValue({
      ...pendingSession,
      status: 'bound',
      bound_at: new Date().toISOString(),
    });

    render(<WechatBindingPanel userId={2} />);

    expect(await screen.findByText('微信学习助手已绑定')).toBeInTheDocument();
    expect(window.sessionStorage.getItem('studybuddy:wechat-bind-session:2')).toBeNull();
    expect(window.localStorage.getItem('studybuddy:wechat-bind-snoozed-on:2')).toBeNull();
  });

  it('lets the student skip without cancelling the pending provider session', async () => {
    const onSkip = vi.fn();
    render(<WechatBindingPanel userId={2} autoStart allowSkip onSkip={onSkip} />);

    fireEvent.click(await screen.findByRole('button', { name: '今天不再提醒' }));

    expect(onSkip).toHaveBeenCalledOnce();
    expect(window.sessionStorage.getItem('studybuddy:wechat-bind-session:2')).toBe('42');
  });

  it('stops polling on skip and ignores in-flight responses so the panel stays closed', async () => {
    vi.useFakeTimers();
    let resolvePoll!: (value: typeof pendingSession) => void;
    mockedWechatApi.getBindSession.mockImplementation(
      () =>
        new Promise<typeof pendingSession>((resolve) => {
          resolvePoll = resolve;
        }),
    );
    const ref = createRef<WechatBindingPanelHandle>();
    render(<WechatBindingPanel ref={ref} userId={2} autoStart allowSkip onSkip={() => {}} />);

    // 初始创建 session 后进入 pending 态
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText('W711966')).toBeInTheDocument();

    // 让首次轮询发起，getBindSession 返回一个未 resolve 的 promise
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(1);

    // skip：停轮询，面板切到重试态，绑定码消失
    act(() => {
      ref.current?.stopPolling();
    });
    expect(screen.queryByText('W711966')).not.toBeInTheDocument();

    // 飞行中的轮询返回 pending：被丢弃，不会回到 pending 态、不会重排轮询
    await act(async () => {
      resolvePoll(pendingSession);
    });
    expect(screen.queryByText('W711966')).not.toBeInTheDocument();

    // 之后不再发起新轮询
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(mockedWechatApi.getBindSession).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});

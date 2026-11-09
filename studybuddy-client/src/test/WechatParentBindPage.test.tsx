import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { wechatApi } from '@/features/wechat/api';
import WechatParentBindPage from '@/features/wechat/pages/WechatParentBindPage';

vi.mock('@/features/wechat/api', () => ({
  wechatApi: {
    getParentInvitation: vi.fn(),
  },
}));

const mockedWechatApi = vi.mocked(wechatApi);

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/wechat-parent-bind?token=scene-token']}>
      <Routes>
        <Route path="/wechat-parent-bind" element={<WechatParentBindPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function invitation(overrides = {}) {
  return {
    parent_name: '测试家长',
    student_name: '测试学生',
    bind_code: 'WABC123',
    qr_value: 'https://example.test/parent-qr-1',
    status: 'pending' as const,
    expires_at: new Date(Date.now() + 180999).toISOString(),
    ...overrides,
  };
}

describe('WechatParentBindPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedWechatApi.getParentInvitation.mockResolvedValue(invitation());
    Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
      configurable: true,
      value: vi.fn(() => 'data:image/png;base64,cXJjb2Rl'),
    });
  });

  it('shows the relationship, qr, bind code and countdown', async () => {
    renderPage();

    expect(await screen.findByText('测试家长')).toBeInTheDocument();
    expect(screen.getByText('测试学生')).toBeInTheDocument();
    expect(screen.getByText('WABC123')).toBeInTheDocument();
    expect(screen.getByText('03:00')).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: '微信学习助手二维码' })).toHaveAttribute(
      'data-qr-value',
      'https://example.test/parent-qr-1',
    );
    expect(screen.queryByText(/公众号|学明白了/)).not.toBeInTheDocument();
  });

  it('refreshes the qr while the invitation is pending', async () => {
    vi.useFakeTimers();
    mockedWechatApi.getParentInvitation
      .mockResolvedValueOnce(invitation())
      .mockResolvedValue(invitation({ qr_value: 'https://example.test/parent-qr-2' }));
    try {
      renderPage();
      await act(async () => Promise.resolve());
      await act(async () => vi.advanceTimersByTimeAsync(3000));

      expect(screen.getByRole('img', { name: '微信学习助手二维码' })).toHaveAttribute(
        'data-qr-value',
        'https://example.test/parent-qr-2',
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries after a transient invitation request failure', async () => {
    vi.useFakeTimers();
    mockedWechatApi.getParentInvitation
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue(invitation());
    try {
      renderPage();
      await act(async () => Promise.resolve());
      expect(screen.getByLabelText('正在加载家长邀请')).toBeInTheDocument();

      await act(async () => vi.advanceTimersByTimeAsync(3000));

      expect(screen.getByText('测试家长')).toBeInTheDocument();
      expect(mockedWechatApi.getParentInvitation).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows the successful terminal state', async () => {
    mockedWechatApi.getParentInvitation.mockResolvedValue(
      invitation({ status: 'bound', expires_at: new Date().toISOString() }),
    );

    renderPage();

    expect(await screen.findByText('绑定成功')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: '微信学习助手二维码' })).not.toBeInTheDocument();
  });

  it('shows the expired terminal state', async () => {
    mockedWechatApi.getParentInvitation.mockResolvedValue(
      invitation({ status: 'expired', expires_at: new Date(Date.now() - 1000).toISOString() }),
    );

    renderPage();

    expect(await screen.findByText('邀请已失效')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: '微信学习助手二维码' })).not.toBeInTheDocument();
  });
});

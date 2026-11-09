import { App as AntdApp } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import { wechatApi } from '@/features/wechat/api';
import FamilyCompanionPage from '@/features/family/pages/FamilyCompanionPage';

vi.mock('@/features/wechat/api', () => ({
  wechatApi: {
    getGuardianSettings: vi.fn(),
    listGuardianContexts: vi.fn(),
    createGuardianInvitation: vi.fn(),
    getBindSession: vi.fn(),
    updateGuardianContext: vi.fn(),
    unbindGuardianContext: vi.fn(),
  },
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: {
      success: vi.fn(),
      error: vi.fn(),
    },
  });
  return { ...actual, App: AppMock };
});

const mockedWechatApi = vi.mocked(wechatApi);

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter>
        <FamilyCompanionPage />
      </MemoryRouter>
    </AntdApp>,
  );
}

describe('FamilyCompanionPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedWechatApi.getGuardianSettings.mockResolvedValue({
      push_time_options: ['20:00', '21:00'],
      default_push_time: '20:30',
    });
    mockedWechatApi.listGuardianContexts.mockResolvedValue([
      {
        id: 7,
        guardian_name: '微信家长',
        openid_masked: 'parent***0001',
        push_time: '20:30',
        paused: false,
        status: 'active',
        latest_summary_title: '今日成长摘要',
        latest_summary_content: '今天完成了函数错题复盘。',
        latest_summary_created_at: '2026-07-12T20:30:00',
      },
    ]);
    mockedWechatApi.updateGuardianContext.mockImplementation(async (_id, payload) => ({
      id: 7,
      guardian_name: '微信家长',
      openid_masked: 'parent***0001',
      push_time: payload.push_time ?? '20:30',
      paused: payload.paused ?? false,
      status: 'active',
      latest_summary_title: '今日成长摘要',
      latest_summary_content: '今天完成了函数错题复盘。',
      latest_summary_created_at: '2026-07-12T20:30:00',
    }));
    mockedWechatApi.unbindGuardianContext.mockResolvedValue(undefined);
    mockedWechatApi.createGuardianInvitation.mockResolvedValue({
      id: 19,
      bind_code: 'WABC234',
      qr_value: 'https://example.test/guardian-invite',
      status: 'pending',
      expires_at: '2026-07-12T13:00:00Z',
      bound_at: null,
    });
    mockedWechatApi.getBindSession.mockResolvedValue({
      id: 19,
      bind_code: 'WABC234',
      qr_value: 'https://example.test/guardian-invite',
      status: 'pending',
      expires_at: '2026-07-12T13:00:00Z',
      bound_at: null,
    });
  });

  it('展示家长、真实摘要并可修改时间和暂停', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('微信家长')).toBeInTheDocument();
    expect(screen.getByText('今天完成了函数错题复盘。')).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '成长摘要发送时间' }));
    const timeLabels = await screen.findAllByText('21:00');
    fireEvent.click(timeLabels[timeLabels.length - 1]);
    await waitFor(() =>
      expect(mockedWechatApi.updateGuardianContext).toHaveBeenCalledWith(7, {
        push_time: '21:00',
      }),
    );

    const pauseButton = screen.getByRole('button', { name: /暂停推送/ });
    await waitFor(() => expect(pauseButton).not.toBeDisabled());
    await user.click(pauseButton);
    await waitFor(() =>
      expect(mockedWechatApi.updateGuardianContext).toHaveBeenCalledWith(7, {
        paused: true,
      }),
    );
  });

  it('生成邀请并展示二维码和绑定码', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /邀请家长/ }));

    expect(await screen.findByLabelText('家长邀请二维码')).toBeInTheDocument();
    expect(screen.getByText('WABC234')).toBeInTheDocument();
  });

  it('支持解除当前家庭陪伴关系', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: '解除绑定' }));
    fireEvent.click(await screen.findByText('确认解除'));

    await waitFor(() => expect(mockedWechatApi.unbindGuardianContext).toHaveBeenCalledWith(7));
  });

  it('显示空态和加载失败后的重试入口', async () => {
    mockedWechatApi.listGuardianContexts.mockRejectedValueOnce(new Error('network'));
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('家庭陪伴加载失败')).toBeInTheDocument();
    mockedWechatApi.listGuardianContexts.mockResolvedValueOnce([]);
    await user.click(screen.getByRole('button', { name: '重新加载' }));

    expect(await screen.findByText('还没有绑定家长')).toBeInTheDocument();
  });
});

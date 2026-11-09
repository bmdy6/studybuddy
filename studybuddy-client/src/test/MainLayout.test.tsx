import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import MainLayout from '@/app/layouts/MainLayout';
import { ROLES } from '@/shared/constants';
import type { Role } from '@/shared/constants';
import { familyGoalApi } from '@/features/family_goal/api';
import type { FamilyTodayTask } from '@/types';

vi.mock('@/features/family_goal/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/family_goal/api')>(
    '@/features/family_goal/api',
  );
  return {
    ...actual,
    familyGoalApi: { ...actual.familyGoalApi, todayTasks: vi.fn().mockResolvedValue([]) },
  };
});

const mockTodayTasks = vi.mocked(familyGoalApi.todayTasks);

function familyTask(overrides: Partial<FamilyTodayTask> = {}): FamilyTodayTask {
  return {
    occurrence_id: 11,
    task_id: 21,
    goal_id: 31,
    student_id: 2,
    title: '默写英语单词',
    description: null,
    goal_title: '英语默写',
    repeat_type: 'once',
    status: 'pending',
    occurrence_date: '2026-09-30',
    reward_amount: '5.00',
    submit_note: null,
    reject_reason: null,
    submitted_at: null,
    reviewed_at: null,
    evidence: [],
    ...overrides,
  };
}

const { mockGetWechatAccount, mockBindingPanelRender } = vi.hoisted(() => ({
  mockGetWechatAccount: vi.fn().mockResolvedValue({ bound: true }),
  mockBindingPanelRender: vi.fn(),
}));

vi.mock('@/features/wechat/api', () => ({
  wechatApi: {
    getAccount: mockGetWechatAccount,
  },
}));

vi.mock('@/features/wechat/components/WechatBindingPanel', () => ({
  wechatBindingReminderStorageKey: (userId: number) =>
    `studybuddy:wechat-bind-snoozed-on:${userId}`,
  default: ({ onSkip }: { onSkip?: () => void }) => {
    mockBindingPanelRender();
    return (
      <button type="button" onClick={onSkip}>
        今天不再提醒
      </button>
    );
  },
}));

let mockAuthVersion = 0;
let mockRole: Role = ROLES.STUDENT;

vi.mock('@/features/growth/notification', () => ({
  notificationApi: {
    list: vi.fn().mockResolvedValue({ items: [], unread_count: 0 }),
    markRead: vi.fn(),
  },
}));

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({
    token: 'token',
    role: mockRole,
    displayName: '测试学生',
    avatar: null,
    userId: 2,
    children: [],
    activeChildId: null,
    authVersion: mockAuthVersion,
    recentAccounts: [],
    logout: vi.fn(),
    switchAccount: vi.fn(),
    forgetAccount: vi.fn(),
    setActiveChild: vi.fn(),
    updateProfile: vi.fn(),
    isAuthenticated: true,
  }),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  const AppMock = ({ children }: { children: ReactNode }) => <>{children}</>;
  AppMock.useApp = () => ({
    message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
    modal: { confirm: vi.fn(), info: vi.fn() },
    notification: { info: vi.fn() },
  });
  return {
    ...actual,
    App: AppMock,
  };
});

function StatefulChild() {
  const [mountedAt] = useState(mockAuthVersion);
  return <div>mounted-version-{mountedAt}</div>;
}

function CurrentPath() {
  return <div data-testid="current-path">{useLocation().pathname}</div>;
}

function renderLayout(path = '/chat') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route path="*" element={<CurrentPath />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function todayKey() {
  const today = new Date();
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const day = String(today.getDate()).padStart(2, '0');
  return `${today.getFullYear()}-${month}-${day}`;
}

describe('MainLayout account switching', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    mockGetWechatAccount.mockClear();
    mockGetWechatAccount.mockResolvedValue({ bound: true });
    mockBindingPanelRender.mockClear();
  });

  it('已绑定学生不会在关闭的引导中挂载绑定面板', async () => {
    renderLayout();

    await screen.findByTestId('current-path');
    expect(mockGetWechatAccount).toHaveBeenCalled();
    expect(mockBindingPanelRender).not.toHaveBeenCalled();
  });
  it('身份版本变化后重新挂载当前页面，避免旧账号内容残留', async () => {
    mockAuthVersion = 0;
    const view = render(
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route path="chat" element={<StatefulChild />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('mounted-version-0')).toBeInTheDocument();

    mockAuthVersion = 1;
    view.rerender(
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route path="chat" element={<StatefulChild />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('mounted-version-1')).toBeInTheDocument();
    expect(screen.queryByText('mounted-version-0')).not.toBeInTheDocument();
  });

  it('家庭陪伴只出现在学生导航，辅导者显示工作台身份', async () => {
    mockRole = ROLES.STUDENT;
    const studentView = renderLayout('/account');
    expect(await screen.findByText('家庭陪伴')).toBeInTheDocument();
    studentView.unmount();

    mockRole = ROLES.PARENT;
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route path="chat" element={<div>对话页</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('辅导者工作台')).toBeInTheDocument();
    expect(screen.queryByText('家庭陪伴')).not.toBeInTheDocument();
    mockRole = ROLES.STUDENT;
  });

  it('学生 Today 侧栏只显示四个直接入口并可进入学习区', async () => {
    mockRole = ROLES.STUDENT;
    const { container } = renderLayout();

    const studentSider = within(container.querySelector('.sb-app-sider') as HTMLElement);
    expect(studentSider.getByText('今天')).toBeInTheDocument();
    const rootItems = Array.from(
      container.querySelectorAll('.sb-app-sider .ant-menu-root > .ant-menu-item'),
    ).map((item) => item.textContent?.trim());

    expect(rootItems).toEqual(['今天', '学习', '成长', '我的']);
    expect(container.querySelector('.sb-app-sider .ant-menu-submenu')).not.toBeInTheDocument();

    fireEvent.click(studentSider.getByText('学习'));
    expect(screen.getByTestId('current-path')).toHaveTextContent('/study-plans');
  });

  it('学生旧页面仍可从二级入口进入', async () => {
    mockRole = ROLES.STUDENT;
    const { container } = renderLayout();
    const studentSider = within(container.querySelector('.sb-app-sider') as HTMLElement);

    fireEvent.click(studentSider.getByText('学习'));
    expect(await screen.findByText('学习计划')).toBeInTheDocument();
    expect(screen.getByText('每日回顾')).toBeInTheDocument();
    expect(screen.getByText('我的试卷')).toBeInTheDocument();
    expect(screen.getByText('错题本')).toBeInTheDocument();
    expect(screen.getByText('笔记')).toBeInTheDocument();
    expect(screen.getByText('素材管理')).toBeInTheDocument();
    expect(screen.getByText('知识地图')).toBeInTheDocument();

    fireEvent.click(studentSider.getByText('每日回顾'));
    expect(screen.getByTestId('current-path')).toHaveTextContent('/daily-review');

    fireEvent.click(studentSider.getByText('成长'));
    expect(await screen.findByText('成长首页')).toBeInTheDocument();
    expect(screen.getByText('学情诊断')).toBeInTheDocument();
    expect(screen.getByText('学习档案')).toBeInTheDocument();

    fireEvent.click(studentSider.getByText('我的'));
    expect(await screen.findByText('家庭陪伴')).toBeInTheDocument();
    expect(screen.getByText('个人中心')).toBeInTheDocument();
    expect(screen.getByText('帮助与更新')).toBeInTheDocument();
  });

  it('访问二级页面时展开并高亮所属分组', async () => {
    mockRole = ROLES.STUDENT;
    const { container } = renderLayout('/error-book');

    // 手机端 Header 也显示「错题本」标题，限定侧栏范围避免多匹配
    const studentSider = within(container.querySelector('.sb-app-sider') as HTMLElement);
    expect(await studentSider.findByText('错题本')).toBeInTheDocument();
    expect(container.querySelector('.ant-menu-submenu-open')?.textContent).toContain('学习');
    expect(container.querySelector('.ant-menu-item-selected')?.textContent).toContain('错题本');
    // 手机端 Header 显示当前页标题
    expect(container.querySelector('.sb-mobile-header-title')?.textContent).toBe('错题本');
  });

  it('每日记录路由属于学习分组并保持导航高亮', async () => {
    mockRole = ROLES.STUDENT;
    const { container } = renderLayout('/daily-records');
    const studentSider = within(container.querySelector('.sb-app-sider') as HTMLElement);

    expect(await studentSider.findByText('每日记录')).toBeInTheDocument();
    expect(container.querySelector('.ant-menu-submenu-open')?.textContent).toContain('学习');
    expect(container.querySelector('.ant-menu-item-selected')?.textContent).toContain('每日记录');
    expect(container.querySelector('.sb-mobile-header-title')?.textContent).toBe('每日记录');
  });

  it('点击二级入口后进入原有页面路由', async () => {
    mockRole = ROLES.STUDENT;
    renderLayout('/error-book');

    fireEvent.click(await screen.findByText('笔记'));
    expect(screen.getByTestId('current-path')).toHaveTextContent('/notes');
  });

  it('辅导者原有一级导航保持不变', async () => {
    mockRole = ROLES.PARENT;
    const { container } = renderLayout();

    await screen.findByText('辅导者工作台');
    const rootItems = Array.from(
      container.querySelectorAll('.sb-app-sider .ant-menu-root > .ant-menu-item, .sb-app-sider .ant-menu-root > .ant-menu-submenu'),
    ).map((item) => item.textContent?.trim());

    expect(rootItems).toEqual(['对话', '学习计划', '学生', '试卷管理', '素材管理', '帮助与更新']);
    mockRole = ROLES.STUDENT;
  });

  it('手机端固定显示四个常用入口，学生不渲染侧边栏 Drawer 和汉堡菜单', async () => {
    mockRole = ROLES.STUDENT;
    renderLayout();

    const mobileNavigation = await screen.findByRole('navigation', { name: '学生快捷导航' });
    expect(mobileNavigation).toHaveTextContent('今天');
    expect(mobileNavigation).toHaveTextContent('学习');
    expect(mobileNavigation).toHaveTextContent('成长');
    expect(mobileNavigation).toHaveTextContent('我的');

    // 学生手机端不再渲染汉堡菜单和侧边 Drawer
    expect(screen.queryByRole('button', { name: '全部功能' })).not.toBeInTheDocument();
    expect(document.querySelector('.sb-mobile-nav-drawer')).not.toBeInTheDocument();
  });

  it('家长手机端仍保留菜单按钮和 Drawer', async () => {
    mockRole = ROLES.PARENT;
    renderLayout('/chat');

    await screen.findByText('辅导者工作台');
    // 家长有汉堡菜单按钮
    const menuBtn = screen.getByRole('button', { name: '全部功能' });
    fireEvent.click(menuBtn);
    // 点击后 Drawer portal 到 body
    await waitFor(() => {
      expect(document.body.querySelector('.sb-mobile-nav-drawer')).toBeInTheDocument();
    });
    mockRole = ROLES.STUDENT;
  });

  it('未绑定学生可以选择今天不再提醒', async () => {
    mockRole = ROLES.STUDENT;
    mockGetWechatAccount.mockResolvedValue({ bound: false });
    renderLayout();

    expect(await screen.findByText('连接微信学习助手')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '今天不再提醒' }));

    expect(window.localStorage.getItem('studybuddy:wechat-bind-snoozed-on:2')).toBe(todayKey());
  });

  it('同一天重新进入时不再请求绑定状态或弹出引导', async () => {
    mockRole = ROLES.STUDENT;
    mockGetWechatAccount.mockResolvedValue({ bound: false });
    window.localStorage.setItem('studybuddy:wechat-bind-snoozed-on:2', todayKey());

    renderLayout();

    await screen.findByTestId('current-path');
    expect(mockGetWechatAccount).not.toHaveBeenCalled();
    expect(mockBindingPanelRender).not.toHaveBeenCalled();
    expect(screen.queryByText('连接微信学习助手')).not.toBeInTheDocument();
  });

  it('之前日期的提醒记录不会阻止今天再次显示绑定引导', async () => {
    mockRole = ROLES.STUDENT;
    mockGetWechatAccount.mockResolvedValue({ bound: false });
    window.localStorage.setItem('studybuddy:wechat-bind-snoozed-on:2', '2000-01-01');

    renderLayout();

    expect(await screen.findByText('连接微信学习助手')).toBeInTheDocument();
    expect(mockGetWechatAccount).toHaveBeenCalledOnce();
  });
});

describe('MainLayout 家庭任务 Badge', () => {
  beforeEach(() => {
    mockRole = ROLES.STUDENT;
    mockTodayTasks.mockReset();
    mockTodayTasks.mockResolvedValue([]);
  });

  async function openFamilyTaskItem() {
    const { container } = renderLayout('/family-tasks');
    const studentSider = within(container.querySelector('.sb-app-sider') as HTMLElement);
    const label = await studentSider.findByText('家庭任务');
    return label.closest('.ant-menu-item') as HTMLElement;
  }

  it('存在待完成家庭任务时「家庭任务」菜单项显示数量', async () => {
    mockTodayTasks.mockResolvedValue([
      familyTask({ status: 'pending' }),
      familyTask({ status: 'rejected', occurrence_id: 12 }),
      familyTask({ status: 'approved', occurrence_id: 13 }),
    ]);

    const item = await openFamilyTaskItem();

    expect(mockTodayTasks).toHaveBeenCalledWith(2);
    expect(within(item).getByText('2')).toBeInTheDocument();
  });

  it('没有待完成家庭任务时不显示数量', async () => {
    mockTodayTasks.mockResolvedValue([familyTask({ status: 'approved' })]);

    const item = await openFamilyTaskItem();

    expect(within(item).queryByText(/^[0-9]+$/)).not.toBeInTheDocument();
  });
});

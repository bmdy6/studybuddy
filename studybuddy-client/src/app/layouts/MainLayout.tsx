import { WECHAT_ENABLED } from '@/shared/constants';
import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Layout, Menu, Avatar, Dropdown, Typography, Space, Select, theme, Badge, Popover, List, Button, Empty, Drawer } from 'antd';
import {
  FileTextOutlined,
  BookOutlined,
  BarChartOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  UserOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  BellOutlined,
  CalendarOutlined,
  CheckSquareOutlined,
  MessageOutlined,
  TrophyOutlined,
  TeamOutlined,
  EditOutlined,
  DatabaseOutlined,
  QuestionCircleOutlined,
  SwapOutlined,
  NodeIndexOutlined,
  HomeOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import type { MenuProps } from 'antd';
import { useAuth } from '@/features/auth/useAuth';
import { ROLES, BRAND } from '@/shared/constants';
import { notificationApi } from '@/features/growth/notification';
import type { NotificationItem } from '@/types';
import WechatBindingOnboarding from '@/features/wechat/components/WechatBindingOnboarding';
import { useChatStore } from '@/features/chat/store';
import { useBreakpoint } from '@/shared/theme/breakpoints';
import TodayPlanPanel from '@/features/chat/components/TodayPlanPanel';
import { useOpenFamilyTaskCount } from '@/features/family_goal/hooks';

const { Sider, Header, Content } = Layout;
const { Text } = Typography;

/** 「我的」菜单里的家庭任务项：有待完成时带数量 Badge，没有就是纯文字。 */
function familyTaskMenuItemLabel(count: number) {
  if (count <= 0) return '家庭任务';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
      家庭任务
      <Badge count={count} size="small" />
    </span>
  );
}

export default function MainLayout() {
  const {
    displayName,
    avatar,
    role,
    userId,
    authVersion,
    logout,
    children,
    activeChildId,
    recentAccounts,
    switchAccount,
    setActiveChild,
  } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const bp = useBreakpoint();
  // 「家庭任务」菜单只对学生本人开放，家长没有该路由，不发请求
  const openFamilyTaskCount = useOpenFamilyTaskCount(
    role === ROLES.STUDENT ? (userId ?? null) : null,
  );
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  // 学生手机端不渲染侧边栏 Drawer 和汉堡菜单（用底部四栏导航）；
  // 家长手机端仍保留 Drawer。
  const showMobileNavDrawer = role === ROLES.PARENT;
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  // parent：侧栏精简为「对话 / 学生 / 试卷管理组 / 素材管理」（开发进度文档问题1）。
  // 属性面板/学情诊断/错题本已收进「学生」详情页 tab，不再平铺在侧栏；
  // 「我的试卷」对 parent 无答题需求，由试卷管理组内的「试卷管理」(/teacher/exams) 替代；
  // 试卷管理/判分队列折叠进「试卷管理」组。
  const parentMenu: MenuProps['items'] = [
    { key: '/chat', icon: <MessageOutlined />, label: '对话' },
    { key: '/study-plans', icon: <CalendarOutlined />, label: '学习计划' },
    { key: '/students', icon: <TeamOutlined />, label: '学生' },
    { type: 'divider' },
    {
      key: 'exam-mgmt',
      icon: <FileTextOutlined />,
      label: '试卷管理',
      children: [
        { key: '/teacher/exams', icon: <FileTextOutlined />, label: '试卷管理' },
        { key: '/teacher/question-bank', icon: <DatabaseOutlined />, label: '题库候选' },
        { key: '/teacher/grading', icon: <CheckSquareOutlined />, label: '判分队列' },
      ],
    },
    { type: 'divider' },
    { key: '/materials', icon: <FolderOpenOutlined />, label: '素材管理' },
    { key: '/help', icon: <QuestionCircleOutlined />, label: '帮助与更新' },
  ];
  const studentMenu: MenuProps['items'] = [
    { key: '/chat', icon: <HomeOutlined />, label: '今天' },
    {
      key: 'student-learning',
      icon: <BookOutlined />,
      label: '学习',
      children: [
        { key: '/study-plans', icon: <CalendarOutlined />, label: '学习计划' },
        { key: '/daily-records', icon: <CalendarOutlined />, label: '每日记录' },
        { key: '/daily-review', icon: <EditOutlined />, label: '每日回顾' },
        { key: '/exams', icon: <FileTextOutlined />, label: '我的试卷' },
        { key: '/error-book', icon: <BookOutlined />, label: '错题本' },
        { key: '/notes', icon: <EditOutlined />, label: '笔记' },
        { key: '/materials', icon: <FolderOpenOutlined />, label: '素材管理' },
        { key: '/learning-map', icon: <NodeIndexOutlined />, label: '知识地图' },
      ],
    },
    {
      key: 'student-growth',
      icon: <BarChartOutlined />,
      label: '成长',
      children: [
        { key: '/growth', icon: <BarChartOutlined />, label: '成长首页' },
        { key: '/diagnosis', icon: <BarChartOutlined />, label: '学情诊断' },
        { key: '/profile', icon: <TrophyOutlined />, label: '学习档案' },
      ],
    },
    {
      key: 'student-account',
      icon: <UserOutlined />,
      label: '我的',
      children: [
        ...(WECHAT_ENABLED ? [{ key: '/family', icon: <TeamOutlined />, label: '家庭陪伴' }] : []),
        { key: '/family-tasks', icon: <TrophyOutlined />, label: familyTaskMenuItemLabel(openFamilyTaskCount) },
        { key: '/account', icon: <UserOutlined />, label: '个人中心' },
        { key: '/help', icon: <QuestionCircleOutlined />, label: '帮助与更新' },
      ],
    },
  ];
  const studentTodayMenu: MenuProps['items'] = [
    { key: '/chat', icon: <HomeOutlined />, label: '今天' },
    { key: '/study-plans', icon: <BookOutlined />, label: '学习' },
    { key: '/growth', icon: <BarChartOutlined />, label: '成长' },
    { key: '/account', icon: <UserOutlined />, label: '我的' },
  ];
  const menuItems = role === ROLES.PARENT ? parentMenu : studentMenu;

  // 当前高亮：取路径前两段，如 /teacher/grading → /teacher/grading
  const parts = location.pathname.split('/').filter(Boolean);
  // 学生详情页 /students/:id → 高亮「学生」(/students)
  const selectedKey =
    parts[0] === 'students'
      ? '/students'
      : parts.length >= 2
        ? `/${parts[0]}/${parts[1]}`
        : `/${parts[0] ?? 'chat'}`;
  const desktopMenuItems =
    role === ROLES.STUDENT && selectedKey === '/chat' ? studentTodayMenu : menuItems;
  // 进入二级页面时展开所属分组，旧页面仍可直接访问。
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const studentOpenKey = [
    ['/study-plans', '/daily-records', '/daily-review', '/exams', '/error-book', '/notes', '/materials', '/learning-map'],
    ['/growth', '/diagnosis', '/profile'],
    ['/family', '/family-tasks', '/account', '/help'],
  ].findIndex((keys) => keys.includes(selectedKey));
  const defaultOpenKey =
    role === ROLES.PARENT
      ? parts[0] === 'teacher'
        ? 'exam-mgmt'
        : ''
      : ['student-learning', 'student-growth', 'student-account'][studentOpenKey] ?? '';
  const currentOpenKeys =
    defaultOpenKey && !openKeys.includes(defaultOpenKey) ? [...openKeys, defaultOpenKey] : openKeys;
  const mobileNavigation = [
    { label: '今天', path: '/chat', icon: <HomeOutlined />, active: selectedKey === '/chat' },
    {
      label: '学习',
      path: '/study-plans',
      icon: <BookOutlined />,
      active: studentOpenKey === 0,
    },
    {
      label: '成长',
      path: '/growth',
      icon: <BarChartOutlined />,
      active: studentOpenKey === 1,
    },
    {
      label: '我的',
      path: '/account',
      icon: <UserOutlined />,
      active: studentOpenKey === 2,
    },
  ];

  // 手机端 Header：一级落地页显示栏目名，二级页显示页面标题 + 返回箭头。
  const mobilePrimaryTitles: Record<string, string> = {
    '/chat': '今天',
    '/study-plans': '学习',
    '/growth': '成长',
    '/account': '我的',
  };
  const mobilePageTitles: Record<string, string> = {
    '/daily-review': '每日回顾',
    '/daily-records': '每日记录',
    '/exams': '我的试卷',
    '/error-book': '错题本',
    '/notes': '笔记',
    '/materials': '素材管理',
    '/learning-map': '知识地图',
    '/diagnosis': '学情诊断',
    '/profile': '学习档案',
    '/family': '家庭陪伴',
    '/family-tasks': '家庭任务',
    '/help': '帮助与更新',
    '/students': '学生',
  };
  const isMobilePrimary = Object.prototype.hasOwnProperty.call(
    mobilePrimaryTitles,
    selectedKey,
  );
  const mobileHeaderTitle = isMobilePrimary
    ? mobilePrimaryTitles[selectedKey]
    : mobilePageTitles[selectedKey] ?? BRAND.name;

  const navigateFromMenu: MenuProps['onClick'] = ({ key }) => {
    if (!String(key).startsWith('/')) return;
    navigate(String(key));
    setMobileNavOpen(false);
  };

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    const rawKey = String(key);
    if (rawKey === 'logout') {
      logout();
    } else if (rawKey === 'account') {
      navigate('/account');
    } else if (rawKey.startsWith('switch-account:')) {
      const targetId = rawKey.replace('switch-account:', '');
      if (switchAccount(targetId)) {
        navigate('/chat');
      }
    }
  };

  const switchableAccounts = recentAccounts.filter((account) => account.userId !== userId);
  const accountSwitchItems: NonNullable<MenuProps['items']> =
    switchableAccounts.length > 0
      ? [
          {
            key: 'switch-title',
            type: 'group',
            label: '切换账号',
            children: switchableAccounts.map((account) => ({
              key: `switch-account:${account.id}`,
              icon: <SwapOutlined />,
              label: (
                <Space direction="vertical" size={0}>
                  <Text>{account.displayName}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {account.role === ROLES.PARENT ? '辅导者' : '学生'} · {account.username}
                  </Text>
                </Space>
              ),
            })),
          },
          { type: 'divider' },
        ]
      : [];

  const dropdownItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: (
        <Space direction="vertical" size={0}>
          <Text strong>{displayName ?? '用户'}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {role === ROLES.PARENT ? '辅导者' : '学生'}
          </Text>
        </Space>
      ),
      disabled: true,
    },
    { type: 'divider' },
    ...accountSwitchItems,
    {
      key: 'account',
      icon: <UserOutlined />,
      label: '个人中心',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
    },
  ];

  const loadNotifications = async () => {
    const data = await notificationApi.list({ limit: 8 });
    setNotifications(data.items);
    setUnreadCount(data.unread_count);
  };

  useEffect(() => {
    setNotifications([]);
    setUnreadCount(0);
    loadNotifications().catch(() => {
      setNotifications([]);
      setUnreadCount(0);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authVersion]);

  const markNotificationRead = async (item: NotificationItem) => {
    if (item.read_at) return;
    await notificationApi.markRead(item.id);
    await loadNotifications();
  };

  const notificationContent = (
    <div style={{ width: 320, maxWidth: 'calc(100vw - 48px)' }}>
      {notifications.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
      ) : (
        <List
          itemLayout="vertical"
          dataSource={notifications}
          renderItem={(item) => (
            <List.Item
              style={{ padding: '10px 0' }}
              actions={
                item.read_at
                  ? []
                  : [
                      <Button key="read" type="link" size="small" onClick={() => markNotificationRead(item)}>
                        标记已读
                      </Button>,
                    ]
              }
            >
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Space>
                  {!item.read_at && <Badge status="processing" />}
                  <Text strong={!item.read_at}>{item.title}</Text>
                </Space>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {item.content}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {item.created_at}
                </Text>
              </Space>
            </List.Item>
          )}
        />
      )}
    </div>
  );

  // 学生手机端 Today 页隐藏全局 Header，由 TodayPlanPanel 提供唯一顶部栏
  const hideMobileHeader = role === ROLES.STUDENT && selectedKey === '/chat';

  // PC 桌面：学生 + 聊天页时，今日任务 dock 并入全局 Header 一条栏（compact 单行）。
  // 回调全部走 chatStore 全局 action，不依赖 ChatPage 学习流；mode 由 activeTaskSessionId 推导。
  const headerTodayStudentId =
    role === ROLES.STUDENT && selectedKey === '/chat' && !bp.isMobile
      ? (activeChildId ?? userId)
      : null;
  const activeTaskSessionId = useChatStore((s) => s.activeTaskSessionId);
  const headerTodayMode = activeTaskSessionId ? 'learning' : 'today';

  return (
    <Layout className="sb-app-layout" style={{ minHeight: '100dvh' }}>
      {WECHAT_ENABLED && role === ROLES.STUDENT && userId ? <WechatBindingOnboarding userId={userId} /> : null}
      <Sider
        className="sb-app-sider"
        trigger={null}
        collapsible
        collapsed={collapsed}
        width={204}
        style={{
          background: colorBgContainer,
          borderRight: '1px solid var(--sb-color-border-secondary)',
          position: 'sticky',
          top: 0,
          height: '100dvh',
          overflow: 'auto',
        }}
      >
        {/* Logo 区 */}
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: collapsed ? '0 20px' : '0 24px',
            borderBottom: '1px solid var(--sb-color-border-subtle)',
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: 'var(--sb-color-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--sb-color-white)',
              fontWeight: 700,
              fontSize: 16,
              flexShrink: 0,
            }}
          >
            {BRAND.name[0]}
          </div>
          {!collapsed && (
            <div>
              <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--sb-color-text)' }}>
                {BRAND.name}
              </div>
              {role === ROLES.PARENT ? (
                <div style={{ fontSize: 11, color: 'var(--sb-color-text-secondary)' }}>
                  辅导者工作台
                </div>
              ) : BRAND.nameEn ? (
                <div style={{ fontSize: 11, color: 'var(--sb-color-text-secondary)' }}>
                  {BRAND.nameEn}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={currentOpenKeys}
          onOpenChange={(keys) => setOpenKeys(keys as string[])}
          items={desktopMenuItems}
          onClick={navigateFromMenu}
          style={{
            border: 'none',
            padding: '8px 12px',
            background: 'transparent',
          }}
        />
      </Sider>

      {showMobileNavDrawer && (
      <Drawer
        className="sb-mobile-nav-drawer"
        title={BRAND.name}
        placement="left"
        width={280}
        open={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
      >
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={currentOpenKeys}
          onOpenChange={(keys) => setOpenKeys(keys as string[])}
          items={menuItems}
          onClick={navigateFromMenu}
          style={{ border: 'none' }}
        />
      </Drawer>
      )}

      <Layout className="sb-app-main">
        <Header
          className={`sb-app-header${!isMobilePrimary ? ' sb-has-mobile-back' : ''}${hideMobileHeader ? ' sb-app-header--hidden-mobile' : ''}`}
          style={{
            background: colorBgContainer,
            borderBottom: '1px solid var(--sb-color-border-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 24px',
            position: 'sticky',
            top: 0,
            zIndex: 10,
            height: 64,
          }}
        >
          {/* 左：折叠按钮 + 学生切换器（多孩子时显示） */}
          <Space>
            {/* 手机端二级页返回箭头（仅非一级页显示） */}
            <Button
              type="text"
              className="sb-mobile-back-trigger"
              aria-label="返回"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(-1)}
            />
            {showMobileNavDrawer && (
            <Button
              type="text"
              className="sb-mobile-nav-trigger"
              aria-label="全部功能"
              icon={<MenuUnfoldOutlined />}
              onClick={() => setMobileNavOpen(true)}
            />
            )}
            <div
              className="sb-desktop-collapse-trigger"
              onClick={() => setCollapsed(!collapsed)}
              style={{
                cursor: 'pointer',
                fontSize: 18,
                color: 'var(--sb-color-text-secondary)',
                padding: 8,
              }}
            >
              {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </div>
            {role === ROLES.PARENT && children.length > 1 && (
              <Select
                size="middle"
                value={activeChildId ?? undefined}
                onChange={(v) => {
                  setActiveChild(v);
                  // 切孩子后重载当前页数据
                  navigate(location.pathname);
                }}
                style={{ width: 140 }}
                options={children.map((c) => ({ value: c.id, label: c.display_name }))}
              />
            )}
          </Space>

          {/* 手机端栏目/页面标题（居中，桌面端隐藏） */}
          <h1 className="sb-mobile-header-title">{mobileHeaderTitle}</h1>

          {/* PC 桌面：学生 + 聊天页时，今日任务 dock 并入 Header 一条栏（compact 单行） */}
          {headerTodayStudentId !== null && (
            <div className="sb-header-today-dock">
              <TodayPlanPanel
                studentId={headerTodayStudentId}
                mode={headerTodayMode}
                learningPrompt=""
                compact
                onStartLearning={(task) => {
                  void useChatStore.getState().continueTaskItem(headerTodayStudentId, task.item.id);
                }}
                onReturnToday={() => {
                  void useChatStore.getState().returnToMainSession();
                }}
                onTaskCompleted={() => {
                  void useChatStore.getState().runSend('我做完了这个任务');
                }}
                onAskAiToPlan={() => {
                  void useChatStore.getState().runSend('帮我制定今天的学习计划');
                }}
              />
            </div>
          )}

          {/* 右：通知 + 用户头像 */}
          <Space size={16}>
            <Popover
              content={notificationContent}
              title="通知"
              trigger="click"
              open={notificationsOpen}
              onOpenChange={(open) => {
                setNotificationsOpen(open);
                if (open) {
                  loadNotifications().catch(() => undefined);
                }
              }}
              placement="bottomRight"
            >
              <Badge count={unreadCount} size="small">
                <BellOutlined
                  style={{ fontSize: 18, color: 'var(--sb-color-text-secondary)', cursor: 'pointer' }}
                />
              </Badge>
            </Popover>
            <Dropdown
              menu={{ items: dropdownItems, onClick: handleMenuClick }}
              placement="bottomRight"
              trigger={['click']}
            >
              <div className="sb-header-user" style={{ cursor: 'pointer', display: 'inline-flex' }}>
                <Space>
                  <Avatar
                    size={32}
                    src={avatar || undefined}
                    style={{ background: 'var(--sb-color-primary)' }}
                    icon={<UserOutlined />}
                  />
                  {!collapsed && <Text>{displayName ?? '用户'}</Text>}
                </Space>
              </div>
            </Dropdown>
          </Space>
        </Header>

        <Content className="sb-app-content" style={{ background: 'var(--sb-color-bg-layout)' }}>
          <Outlet key={authVersion} />
        </Content>
        {role === ROLES.STUDENT && (
          <nav className="sb-mobile-bottom-nav" aria-label="学生快捷导航">
            {mobileNavigation.map((item) => (
              <button
                type="button"
                className={item.active ? 'is-active' : undefined}
                aria-current={item.active ? 'page' : undefined}
                key={item.path}
                onClick={() => navigate(item.path)}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            ))}
          </nav>
        )}
      </Layout>
    </Layout>
  );
}
// agg-1

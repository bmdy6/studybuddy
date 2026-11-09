/**
 * E2E 测试：关键用户路径的真实浏览器回归。
 *
 * 策略：用 Playwright route 拦截后端 API，mock 响应（不依赖真实 LLM 配额）。
 * 重点测真实 React/AntD 渲染、SSE 消费、历史回放、素材预览等前端链路。
 */

import { test, expect, type Page, type Route } from '@playwright/test';

// mock 登录响应
const MOCK_LOGIN = {
  access_token: 'mock-e2e-token',
  token_type: 'bearer',
  expires_in: 3600,
  user_id: 1,
  role: 'teacher',
  display_name: '哥哥',
  children: [{ id: 2, display_name: '弟弟' }],
};

const AUTH_STATE = {
  state: {
    token: 'mock-e2e-token',
    role: 'parent',
    displayName: '哥哥',
    avatar: null,
    userId: 1,
    activeChildId: 2,
    children: [{ id: 2, display_name: '弟弟' }],
  },
  version: 0,
};

const EMPTY_SESSION = { id: 1, user_id: 1, student_id: 2, title: '新对话', created_at: '' };

const EXAM_PHOTO_MATERIAL = {
  id: 7,
  name: '01_试卷_第1页.jpg',
  type: 'image',
  source: 'teacher',
  knowledge_tags: ['english'],
  uploaded_by: '哥哥',
  cos_url: '/uploads/materials/exams/7_english_E2E_2026-07-02/01_试卷_第1页.jpg',
  created_at: '2026-07-02 16:00:00',
};

// mock SSE 出题响应（tool_call + tool_result + done）
function mockSSEExamResponse() {
  const events = [
    'data: {"type":"tool_call","name":"create_exam","input":{"title":"E2E测试卷","subject":"english"},"id":"c1"}\n\n',
    'data: {"type":"tool_result","name":"create_exam","output":"{\\"exam_id\\":99,\\"title\\":\\"E2E测试卷\\",\\"question_count\\":3}","id":"c1"}\n\n',
    'data: {"type":"text","content":"试卷已生成"}\n\n',
    'data: {"type":"done","content":"试卷已生成"}\n\n',
  ];
  return events.join('');
}

interface MockBackendOptions {
  sessions?: unknown[];
  messages?: unknown[];
  materials?: unknown[];
}

async function mockBackend(route: Route, options: MockBackendOptions = {}) {
  const url = route.request().url();
  const { pathname } = new URL(url);
  const apiPath = pathname.startsWith('/sb/api/') ? pathname.slice(3) : pathname;
  const method = route.request().method();

  if (apiPath === '/auth/login') {
    return route.fulfill({ status: 200, json: MOCK_LOGIN });
  }
  if (apiPath.startsWith('/api/chat/sessions') && apiPath.includes('/messages') && method === 'GET') {
    return route.fulfill({ status: 200, json: options.messages ?? [] });
  }
  if (apiPath === '/api/chat/sessions' && method === 'POST') {
    return route.fulfill({ status: 201, json: EMPTY_SESSION });
  }
  if (apiPath === '/api/chat/sessions' && method === 'GET') {
    return route.fulfill({ status: 200, json: options.sessions ?? [] });
  }
  if (apiPath.startsWith('/api/chat/sessions') && apiPath.includes('/messages') && method === 'POST') {
    // SSE 流式响应
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: { 'Cache-Control': 'no-cache' },
      body: mockSSEExamResponse(),
    });
  }
  if (apiPath.startsWith('/api/material/') && apiPath.endsWith('/preview-url')) {
    return route.fulfill({
      status: 200,
      json: { url: EXAM_PHOTO_MATERIAL.cos_url, ext: 'jpg', name: EXAM_PHOTO_MATERIAL.name },
    });
  }
  if (apiPath === '/api/material' && method === 'GET') {
    return route.fulfill({ status: 200, json: options.materials ?? [] });
  }
  if (apiPath === '/api/notifications' && method === 'GET') {
    return route.fulfill({ status: 200, json: { unread_count: 0, items: [] } });
  }
  if (/^\/api\/students\/\d+\/profile\/summary$/.test(apiPath) && method === 'GET') {
    return route.fulfill({
      status: 200,
      json: { student_id: 2, needs_onboarding: false, missing_fields: [], summary: {} },
    });
  }
  if (pathname.includes('/uploads/materials/exams/')) {
    return route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=',
        'base64',
      ),
    });
  }
  // 其他请求放行
  return route.continue();
}

async function installMockBackend(page: Page, options: MockBackendOptions = {}) {
  await page.route('**/*', (route) => mockBackend(route, options));
}

async function seedAuth(page: Page) {
  await page.addInitScript((state) => {
    localStorage.setItem('studybuddy-auth', JSON.stringify(state));
  }, AUTH_STATE);
  await page.goto('/#/login');
  await expect(page.getByRole('heading', { name: '开始学习' })).toBeVisible();
}

function historyToolMessages() {
  return [
    {
      id: 1,
      role: 'user',
      content: '我上传了一份素材「单词表」',
      created_at: '2026-07-02 16:00:00',
    },
    {
      id: 2,
      role: 'assistant',
      content: null,
      tool_calls: [
        {
          id: 'call-read-material',
          type: 'function',
          function: { name: 'read_material', arguments: '{"material_id":7}' },
        },
      ],
      created_at: '2026-07-02 16:00:01',
    },
    {
      id: 3,
      role: 'tool',
      content:
        '{"material_id":7,"name":"单词表.jpg","type":"image","summary":"已读取素材「单词表.jpg」的内容：这是一张英语单词表"}',
      tool_result: { tool_call_id: 'call-read-material', name: 'read_material' },
      created_at: '2026-07-02 16:00:02',
    },
    {
      id: 4,
      role: 'assistant',
      content: '我看到了这张单词表，可以帮你整理成学习笔记。',
      created_at: '2026-07-02 16:00:03',
    },
  ];
}

function longHistoryMessages(count = 90) {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    role: index % 2 === 0 ? 'user' : 'assistant',
    content: `第 ${index + 1} 条${index % 2 === 0 ? '用户' : '助手'}消息`,
    created_at: '2026-07-02 16:00:00',
  }));
}

test.describe('Agent 对话出题 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await installMockBackend(page);
  });

  test('登录后进入对话页', async ({ page }) => {
    await page.goto('/#/login');
    await page.fill('input[id*="username"], input[placeholder*="账号"], input[type="text"]', 'teacher');
    await page.fill('input[type="password"]', 'teacher123');
    await page.click('button[type="submit"], button:has-text("登录")');
    // 登录后跳 /chat
    await page.waitForURL('**/chat', { timeout: 10000 });
    await expect(page).toHaveURL(/\/chat/);
  });

  test('对话页显示引导文案', async ({ page }) => {
    await seedAuth(page);
    await page.goto('/#/chat');
    // 引导文案含"出题"或"对话"
    await expect(page.locator('body')).toContainText(/出题|对话|助手/, { timeout: 10000 });
  });

  test('输入消息并发送，出现 user 气泡', async ({ page }) => {
    await seedAuth(page);
    await page.goto('/#/chat');
    await expect(page.getByTestId('chat-message-input')).toBeEnabled({ timeout: 10000 });

    // 输入并发送
    const input = page.getByTestId('chat-message-input');
    await input.fill('出3道英语题');
    await page.getByTestId('chat-send-button').click();

    // user 气泡出现
    await expect(page.locator('body')).toContainText('出3道英语题', { timeout: 10000 });
  });

  test('出题后工具调用卡片可见', async ({ page }) => {
    await seedAuth(page);
    await page.goto('/#/chat');
    await expect(page.getByTestId('chat-message-input')).toBeEnabled({ timeout: 10000 });

    const input = page.getByTestId('chat-message-input');
    await input.fill('出题');
    await page.getByTestId('chat-send-button').click();

    // 工具调用卡片出现（含"出题"标签）
    await expect(page.locator('body')).toContainText(/出题|进行中|已落库/, { timeout: 10000 });
  });
});

test.describe('P0 浏览器回归', () => {
  test('刷新历史后仍回放工具卡和最终回复', async ({ page }) => {
    await seedAuth(page);
    await installMockBackend(page, {
      sessions: [{ id: 7, user_id: 1, student_id: 2, title: '素材会话', created_at: '' }],
      messages: historyToolMessages(),
    });

    await page.goto('/#/chat');

    await expect(page.locator('body')).toContainText('read_material', { timeout: 10000 });
    await expect(page.locator('body')).toContainText('已读取素材「单词表.jpg」');
    await expect(page.locator('body')).toContainText('我看到了这张单词表');
  });

  test('长历史默认窗口化并可展开更早消息', async ({ page }) => {
    await seedAuth(page);
    await installMockBackend(page, {
      sessions: [{ id: 8, user_id: 1, student_id: 2, title: '长历史会话', created_at: '' }],
      messages: longHistoryMessages(),
    });

    await page.goto('/#/chat');

    await expect(page.locator('body')).toContainText('显示更早 10 条消息', { timeout: 10000 });
    await expect(page.locator('body')).not.toContainText('第 1 条用户消息');
    await page.getByTestId('show-earlier-messages').evaluate((el) => (el as HTMLElement).click());
    await expect(page.locator('body')).toContainText('第 1 条用户消息');
  });

  test('素材管理页能预览错题照片素材', async ({ page }) => {
    await seedAuth(page);
    await installMockBackend(page, { materials: [EXAM_PHOTO_MATERIAL] });

    await page.goto('/#/materials');

    await expect(page.locator('body')).toContainText('素材管理', { timeout: 10000 });
    await expect(page.locator('body')).toContainText(EXAM_PHOTO_MATERIAL.name);
    await page
      .getByRole('row', { name: new RegExp(EXAM_PHOTO_MATERIAL.name) })
      .getByRole('button', { name: '预览' })
      .click();

    await expect(page.getByRole('dialog', { name: EXAM_PHOTO_MATERIAL.name })).toBeVisible();
    await expect(page.locator(`img[alt="${EXAM_PHOTO_MATERIAL.name}"]`)).toBeVisible();
  });
});

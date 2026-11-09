/**
 * E2E：AI 流式输出/工具执行进行中切走再切回，进行中状态与结果不丢失。
 *
 * 这是本分支修复的核心 bug：原来运行态放在 ChatPage useState，路由切换卸载组件后
 * 后台 SSE 流仍在写但目标已丢失，切回来"正在使用工具"状态消失、回复丢失。
 * 现在运行态搬进 zustand chatStore 单例，流在 store action 里跑，切页不影响。
 *
 * 验证手段：mock SSE POST 的 route handler 延迟 1.2s 再返回，制造"进行中"窗口；
 * 期间切到 /materials 再切回 /chat，断言后台流已跑完、结果保留、loading 复位。
 */

import { test, expect, type Page, type Route } from '@playwright/test';

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

// SSE 出题响应（tool_call + tool_result + text + done）
function mockSSEExamResponse() {
  const events = [
    'data: {"type":"tool_call","name":"create_exam","input":{"title":"切页回归卷","subject":"english"},"id":"c1"}\n\n',
    'data: {"type":"tool_result","name":"create_exam","output":"{\\"exam_id\\":99,\\"title\\":\\"切页回归卷\\"}","id":"c1"}\n\n',
    'data: {"type":"text","content":"试卷已生成"}\n\n',
    'data: {"type":"done","content":"试卷已生成"}\n\n',
  ];
  return events.join('');
}

// SSE 请求延迟（ms）：制造"进行中"窗口，期间切走
const SSE_DELAY_MS = 1200;

async function mockBackend(route: Route) {
  const url = route.request().url();
  const { pathname } = new URL(url);
  const apiPath = pathname.startsWith('/sb/api/') ? pathname.slice(3) : pathname;
  const method = route.request().method();

  if (apiPath === '/auth/login') {
    return route.fulfill({ status: 200, json: MOCK_LOGIN });
  }
  if (apiPath.startsWith('/api/chat/sessions') && apiPath.includes('/messages') && method === 'GET') {
    return route.fulfill({ status: 200, json: [] });
  }
  if (apiPath === '/api/chat/sessions' && method === 'POST') {
    return route.fulfill({ status: 201, json: EMPTY_SESSION });
  }
  if (apiPath === '/api/chat/sessions' && method === 'GET') {
    return route.fulfill({ status: 200, json: [] });
  }
  if (apiPath.startsWith('/api/chat/sessions') && apiPath.includes('/messages') && method === 'POST') {
    // 延迟返回，制造"AI 正在输出/使用工具"的进行中窗口
    await new Promise((r) => setTimeout(r, SSE_DELAY_MS));
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: { 'Cache-Control': 'no-cache' },
      body: mockSSEExamResponse(),
    });
  }
  if (apiPath === '/api/material' && method === 'GET') {
    return route.fulfill({ status: 200, json: [] });
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
  return route.continue();
}

async function seedAuth(page: Page) {
  await page.addInitScript((state) => {
    localStorage.setItem('studybuddy-auth', JSON.stringify(state));
  }, AUTH_STATE);
}

test.describe('切页保留进行中的对话状态', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/*', (route) => mockBackend(route));
  });

  test('AI 使用工具进行中切走再切回，结果保留且 loading 复位', async ({ page }) => {
    await seedAuth(page);
    await page.goto('/#/chat');
    await expect(page.getByTestId('chat-message-input')).toBeEnabled({ timeout: 10000 });

    // 发消息 -> 触发 SSE（route 延迟 1.2s，进入"进行中"）
    await page.getByTestId('chat-message-input').fill('出题');
    await page.getByTestId('chat-send-button').click();
    // 等 runSend 起步（loading=true、推入 user 气泡、fetch 已发出）
    await page.waitForTimeout(100);

    // 进行中切到素材页
    await page.goto('/#/materials');
    await expect(page.locator('body')).toContainText('素材管理', { timeout: 10000 });

    // 等后台 SSE 流跑完（delay + 消费）
    await page.waitForTimeout(SSE_DELAY_MS + 800);

    // 切回对话页
    await page.goto('/#/chat');

    // user 气泡仍在
    await expect(page.locator('body')).toContainText('出题', { timeout: 10000 });
    // agent 回复/工具卡仍在（后台流在卸载后跑完写入 store，重挂载后可见）
    await expect(page.locator('body')).toContainText(/create_exam|试卷已生成|进行中|已落库/, {
      timeout: 10000,
    });
    // loading 已复位：输入框重新可用
    await expect(page.getByTestId('chat-message-input')).toBeEnabled({ timeout: 10000 });
  });
});

/**
 * E2E 验收：工具卡片折叠态高度一致 + 长内容单行截断。
 *
 * 策略：mock 后端历史消息，直接渲染含长短 summary 的两张工具卡，
 * 断言标题行真实 offsetHeight 相等、长摘要被 CSS 省略号截断，并截图。
 * 不依赖真实 LLM，只验证前端渲染层。
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

const EMPTY_SESSION = { id: 1, user_id: 1, student_id: 2, title: '工具卡高度验收', created_at: '' };

// 一条 assistant 历史：带两张工具卡（短 summary + 长 summary）
function historyWithTwoToolCards() {
  const longSummaryObj = { note: '这是一段非常长的学习总结内容'.repeat(8) };
  return [
    { id: 1, role: 'user', content: '查一下学情', created_at: '' },
    {
      id: 2,
      role: 'assistant',
      content: null,
      tool_calls: [
        {
          id: 'call-short',
          type: 'function',
          function: { name: 'query_learning_map', arguments: '{}' },
        },
        {
          id: 'call-long',
          type: 'function',
          function: { name: 'query_diagnosis', arguments: '{}' },
        },
      ],
      created_at: '',
    },
    {
      id: 3,
      role: 'tool',
      content: JSON.stringify({ summary: { weak: 1, reviewing: 0, stable: 0 } }),
      tool_result: { tool_call_id: 'call-short', name: 'query_learning_map' },
      created_at: '',
    },
    {
      id: 4,
      role: 'tool',
      content: JSON.stringify({ summary: longSummaryObj }),
      tool_result: { tool_call_id: 'call-long', name: 'query_diagnosis' },
      created_at: '',
    },
    {
      id: 5,
      role: 'assistant',
      content: '已查询完毕。',
      created_at: '',
    },
  ];
}

async function mockBackend(route: Route) {
  const url = route.request().url();
  const { pathname } = new URL(url);
  const apiPath = pathname.startsWith('/sb/api/') ? pathname.slice(3) : pathname;
  const method = route.request().method();

  if (apiPath === '/auth/login') {
    return route.fulfill({ status: 200, json: MOCK_LOGIN });
  }
  if (apiPath === '/api/chat/sessions' && method === 'POST') {
    return route.fulfill({ status: 201, json: EMPTY_SESSION });
  }
  if (apiPath === '/api/chat/sessions' && method === 'GET') {
    return route.fulfill({ status: 200, json: [EMPTY_SESSION] });
  }
  if (apiPath.startsWith('/api/chat/sessions') && apiPath.includes('/messages') && method === 'GET') {
    return route.fulfill({ status: 200, json: historyWithTwoToolCards() });
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

test.describe('工具卡片高度一致 + 内容截断', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/*', (route) => mockBackend(route));
  });

  test('两张工具卡折叠态标题行真实高度相等', async ({ page }) => {
    await seedAuth(page);
    await page.goto('/#/chat');

    // 等待历史回放渲染出两张工具卡（短摘要先出现）
    await expect(page.getByText('查询学习地图')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('查询学情')).toBeVisible({ timeout: 10000 });

    // 工具卡标题行：通过工具名 span 定位其所在的可点击标题行（ancestor div）
    const shortHeader = page.locator('span:has-text("查询学习地图")').locator('xpath=ancestor::div[contains(@style,"cursor: pointer")][1]');
    const longHeader = page.locator('span:has-text("查询学情")').locator('xpath=ancestor::div[contains(@style,"cursor: pointer")][1]');
    await expect(shortHeader).toBeVisible({ timeout: 5000 });
    await expect(longHeader).toBeVisible({ timeout: 5000 });

    const heights = await Promise.all([
      shortHeader.evaluate((el) => (el as HTMLElement).offsetHeight),
      longHeader.evaluate((el) => (el as HTMLElement).offsetHeight),
    ]);
    // 两张卡折叠态高度一致
    expect(heights[0]).toBe(heights[1]);
    // 且等于设定的 40px
    expect(heights[0]).toBe(40);
  });

  test('长 summary 被单行省略号截断，不撑高卡片', async ({ page }) => {
    await seedAuth(page);
    await page.goto('/#/chat');

    await expect(page.getByText('查询学情')).toBeVisible({ timeout: 10000 });

    // 长摘要节点：含省略号结尾
    const longHeader = page.locator('span:has-text("查询学情")').locator('xpath=ancestor::div[contains(@style,"cursor: pointer")][1]');
    const text = (await longHeader.textContent()) || '';
    // summary 被截断到 30 字 + 省略号
    expect(text).toContain('…');
    // 完整长 JSON 串不应在折叠态显示
    expect(text).not.toContain('这是一段非常长的学习总结内容'.repeat(8));

    // 截图存证
    await page.screenshot({ path: 'e2e/screenshots/tool-card-height.png', fullPage: false });
  });
});

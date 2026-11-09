/**
 * E2E 验收：AI 整理笔记 -> 对话里渲染草案卡 -> 「就这样存」/「改一下」后转正式笔记。
 * 用 Playwright route mock 后端 API + SSE，不依赖真实 LLM 配额。
 * 重点测真实 React/AntD 渲染、SSE 消费、草案卡交互、确认调用 update API。
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

const SAVE_NOTE_OUTPUT = {
  id: 2268,
  title: '一般过去时易错点',
  subject: '英语',
  category: '语法',
  content: '# 一般过去时易错点\n\n## 我学到了什么\n- 规则动词过去式加 ed\n- 不规则动词单独记',
  knowledge_tags: ['一般过去时', '规则动词'],
  source: '其他',
  status: 'draft',
  saved: true,
  note_draft: true,
  summary: '已落笔记草稿「一般过去时易错点」（分类：语法），status=draft 待确认。',
};

function mockSSESaveNote() {
  const output = JSON.stringify(SAVE_NOTE_OUTPUT);
  const events = [
    `data: {"type":"tool_call","name":"save_note","input":{"title":"一般过去时易错点","subject":"英语","category":"语法"},"id":"call-save-note"}\n\n`,
    `data: {"type":"tool_result","name":"save_note","output":${JSON.stringify(output)},"id":"call-save-note"}\n\n`,
    `data: {"type":"text","content":"我整理了一版笔记，你看看对不对"}\n\n`,
    `data: {"type":"done","content":"我整理了一版笔记，你看看对不对"}\n\n`,
  ];
  return events.join('');
}

async function seedAuth(page: Page) {
  await page.addInitScript((state) => {
    localStorage.setItem('studybuddy-auth', JSON.stringify(state));
  }, AUTH_STATE);
}

async function mockBackend(
  route: Route,
  ctx: { updates: { path: string; body: unknown }[] },
  messages: unknown[] = [],
) {
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
    return route.fulfill({ status: 200, json: messages });
  }
  if (apiPath.startsWith('/api/chat/sessions') && apiPath.includes('/messages') && method === 'POST') {
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: { 'Cache-Control': 'no-cache' },
      body: mockSSESaveNote(),
    });
  }
  if (/^\/api\/notes\/\d+$/.test(apiPath) && (method === 'PATCH' || method === 'PUT')) {
    ctx.updates.push({ path: apiPath, body: route.request().postDataJSON() });
    return route.fulfill({ status: 200, json: { id: 2268, status: 'confirmed' } });
  }
  if (/^\/api\/notes\/\d+$/.test(apiPath) && method === 'GET') {
    return route.fulfill({ status: 200, json: SAVE_NOTE_OUTPUT });
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

async function sendNoteMessage(page: Page, ctx: { updates: { path: string; body: unknown }[] }) {
  await page.route('**/*', (route) => mockBackend(route, ctx));
  await seedAuth(page);
  await page.goto('/#/chat');
  await expect(page.getByTestId('chat-message-input')).toBeEnabled({ timeout: 10000 });
  await page.getByTestId('chat-message-input').fill('帮我保存笔记');
  await page.getByTestId('chat-send-button').click();
}

test.describe('笔记草案卡 E2E', () => {
  test('save_note 后渲染草案卡，点「就这样存」调用 update 转 confirmed', async ({ page }) => {
    const ctx = { updates: [] as { path: string; body: unknown }[] };
    await sendNoteMessage(page, ctx);

    const panel = page.locator('.sb-note-draft-panel');
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(panel).toContainText('一般过去时易错点');
    await expect(panel).toContainText('语法');
    await expect(panel).toContainText('待确认');
    await expect(page.getByRole('button', { name: /就这样存/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /改一下/ })).toBeVisible();

    await page.getByRole('button', { name: /就这样存/ }).click();

    await expect.poll(() => ctx.updates.length).toBeGreaterThan(0);
    expect(ctx.updates[0].body).toMatchObject({ status: 'confirmed' });
    await expect(page.locator('body')).toContainText('已保存为正式笔记');
  });

  test('点「改一下」编辑后「保存入库」带编辑字段调用 update', async ({ page }) => {
    const ctx = { updates: [] as { path: string; body: unknown }[] };
    await sendNoteMessage(page, ctx);

    const panel = page.locator('.sb-note-draft-panel');
    await expect(panel).toBeVisible({ timeout: 10000 });

    await page.getByRole('button', { name: /改一下/ }).click();
    const titleInput = panel.locator('input').first();
    await titleInput.fill('编辑后的标题');
    await page.getByRole('button', { name: /保存入库/ }).click();

    await expect.poll(() => ctx.updates.length).toBeGreaterThan(0);
    expect(ctx.updates[0].body).toMatchObject({ title: '编辑后的标题', status: 'confirmed' });
  });
});

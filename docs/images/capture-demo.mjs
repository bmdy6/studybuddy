// Run after seed-demo.py, with the API at :18083 and Vite at :15183.
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const require = createRequire(new URL('../../studybuddy-client/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const dir = fileURLToPath(new URL('.', import.meta.url));
const origin = process.env.DEMO_CLIENT_ORIGIN || 'http://127.0.0.1:15183';
const browser = await chromium.launch({headless:true});
const receipts = [];
try {
  for (const [name, route, state, width, height] of [
    ['overview', '/#/study-plans', 'plan', 1440, 900],
    ['plan-confirm', '/#/chat', 'plan', 1280, 800],
    ['task-session', '/#/chat', 'task', 1280, 800],
    ['resume', '/#/study-plans/all', 'plan', 1280, 800],
    ['mobile-task', '/#/chat', 'task', 390, 844],
    ['mobile-plan', '/#/study-plans', 'plan', 390, 844],
    ['mobile-notes', '/#/notes', 'plan', 390, 844],
  ]) {
    const context = await browser.newContext({storageState:dir+state+'-state.private.json',viewport:{width,height},deviceScaleFactor:1});
    const page = await context.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin+route);await page.waitForLoadState('networkidle');
    await page.screenshot({path:dir+name+'.png'});
    const text = await page.locator('body').innerText();
    if (!text.includes('分数')) throw new Error(name+': missing fixture learning content');
    if (errors.length) throw new Error(errors.join('\n'));
    receipts.push({name,route,width,height,sha256:createHash('sha256').update(await readFile(dir+name+'.png')).digest('hex')});
    await context.close();
  }
  // This image is explicitly a chat illustration, using actual deterministic service output.
  const page = await browser.newPage({viewport:{width:600,height:670},deviceScaleFactor:1});
  await page.setContent('<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><style>body{margin:0;background:#ededed;color:#252525;font:18px -apple-system,BlinkMacSystemFont,sans-serif}header{text-align:center;background:#f7f7f7;padding:24px;border-bottom:1px solid #ddd;font-weight:600}.time{text-align:center;font-size:13px;color:#777;margin:24px}.row{display:flex;gap:12px;padding:0 24px}.avatar{background:#266e5c;color:white;width:44px;height:44px;line-height:44px;text-align:center;border-radius:8px;flex-shrink:0}.bubble{white-space:pre-wrap;background:white;border-radius:8px;padding:18px;line-height:1.8}footer{font-size:13px;color:#666;text-align:center;margin:30px}</style><header>知了 · 智学伴</header><p class="time">今天 20:00</p><div class="row"><div class="avatar">知</div><div class="bubble" id="message"></div></div><footer>微信日报示意 · 全部为虚构数据<br>文本由 build_parent_daily_summary 生成</footer></html>');
  await page.locator('#message').textContent();
  await page.evaluate(text=>document.querySelector('#message').textContent=text,await readFile(dir+'parent-summary.txt','utf8'));
  await page.screenshot({path:dir+'wechat-daily-demo.png'});
  await writeFile(dir+'capture-receipt.json',JSON.stringify({browser:browser.version(),synthetic:true,modelCalls:0,shots:receipts},null,2)+'\n');
} finally {await browser.close();}

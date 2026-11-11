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
const chatOnly = process.env.DEMO_CHAT_ONLY === '1';
const receipts = chatOnly ? JSON.parse(await readFile(dir+'capture-receipt.json', 'utf8')).shots.filter(shot=>shot.route) : [];
try {
  for (const [name, route, state, width, height] of chatOnly ? [] : [
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
  // Chat illustrations: only the message layout is synthetic, never the service text.
  const daily = await readFile(dir+'parent-summary.txt', 'utf8');
  const query = await readFile(dir+'parent-query.txt', 'utf8');
  for (const [name, conversation] of [['wechat-daily-demo', false], ['wechat-conversation-demo', true]]) {
    const page = await browser.newPage({viewport:{width:640,height:800},deviceScaleFactor:1});
    await page.setContent(`<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><style>
      *{box-sizing:border-box}body{margin:0;background:#ededed;color:#252525;font:18px -apple-system,BlinkMacSystemFont,sans-serif}
      header{text-align:center;background:#f7f7f7;padding:22px;border-bottom:1px solid #ddd;font-weight:600;font-size:21px}
      .time{text-align:center;font-size:13px;color:#777;margin:20px}.row{display:flex;gap:12px;padding:0 24px;margin-bottom:18px;align-items:flex-start}
      .avatar{background:#266e5c;color:white;width:42px;height:42px;line-height:42px;text-align:center;border-radius:8px;flex-shrink:0}
      .bubble{white-space:pre-wrap;background:white;border-radius:8px;padding:16px;line-height:1.65;max-width:518px}
      .parent{flex-direction:row-reverse}.parent .avatar{background:#a67438}.parent .bubble{background:#a9e879}
      footer{font-size:13px;color:#666;text-align:center;padding:12px 24px 26px;line-height:1.7}main{padding-bottom:2px}
    </style><header>知了</header><main id="chat"></main><footer>微信${conversation?'对话':'日报'}示意 · 全部为虚构数据 · 非微信实发截图<br>正文由真实服务函数生成，学习用时来自学生自报</footer></html>`);
    await page.evaluate(({daily,query,conversation})=>{
      const chat=document.querySelector('#chat');
      function time(text){const el=document.createElement('p');el.className='time';el.textContent=text;chat.append(el)}
      function bubble(text,parent=false){const row=document.createElement('div');row.className='row'+(parent?' parent':'');const avatar=document.createElement('div');avatar.className='avatar';avatar.textContent=parent?'家':'知';const body=document.createElement('div');body.className='bubble';body.textContent=text;row.append(avatar,body);chat.append(row)}
      if(conversation){time('今天 18:10 · 家长主动查询');bubble('今天学得怎么样',true);bubble(query)}
      time('今天 20:00 · 定时日报');bubble(daily);
    },{daily,query,conversation});
    await page.screenshot({path:dir+name+'.png',fullPage:true});
    receipts.push({name,source:conversation?['build_guardian_today_learning_summary','build_parent_daily_summary']:['build_parent_daily_summary'],width:640,height:await page.locator('body').evaluate(el=>el.scrollHeight),sha256:createHash('sha256').update(await readFile(dir+name+'.png')).digest('hex')});
    await page.close();
  }
  await writeFile(dir+'capture-receipt.json',JSON.stringify({browser:browser.version(),synthetic:true,modelCalls:0,shots:receipts},null,2)+'\n');
} finally {await browser.close();}

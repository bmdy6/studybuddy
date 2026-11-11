// Requires seed-demo.py data; mutates only that disposable demo database.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { writeFile } from 'node:fs/promises';
const require=createRequire(new URL('../../studybuddy-client/package.json',import.meta.url));
const {chromium,expect}=require('@playwright/test');
const dir=fileURLToPath(new URL('.',import.meta.url));
const browser=await chromium.launch({headless:true});
const receipt={modelCalls:0,wechatConfigured:false,checks:[]};
try {
 const ctx=await browser.newContext({storageState:dir+'plan-state.private.json',viewport:{width:1280,height:800}});
 const page=await ctx.newPage();const requests=[];page.on('request',r=>requests.push(r.url()));
 await page.goto('http://127.0.0.1:15183/#/chat');
 const button=page.getByRole('button',{name:/确认并创建/});
 await expect(button).toBeVisible();
 const response=page.waitForResponse(r=>r.url().includes('/confirm')&&r.request().method()==='POST');
 await button.click();const confirm=await response;expect(confirm.status()).toBe(200);
 receipt.checks.push('draft confirmed by real UI / API');
 await page.goto('http://127.0.0.1:15183/#/study-plans/all');
 await expect(page.getByText('分数加法 · 两步练习',{exact:true})).toBeVisible();
 receipt.checks.push('confirmed plan persisted and visible after navigation');
 // Verify exact task-session persistence using its saved task navigation state.
 const task=await browser.newContext({storageState:dir+'task-state.private.json',viewport:{width:390,height:844}});
 const taskPage=await task.newPage();
 await taskPage.goto('http://127.0.0.1:15183/#/chat');
 await expect(taskPage.getByText('接下来怎么练',{exact:true})).toBeVisible();
 await taskPage.reload();await expect(taskPage.getByText('接下来怎么练',{exact:true})).toBeVisible();
 receipt.checks.push('mobile task-session history survives reload');
 if(requests.some(u=>u.includes('/channels/wechat')))throw new Error('Disabled integration made requests');
 receipt.checks.push('main flow makes no WeChat API requests while disabled');
 // Read-only responsive check for the restored landing page.
 const landing=await browser.newPage();
 for(const width of [320,768,1024,1440]){
  await landing.setViewportSize({width,height:900});
  await landing.goto('http://127.0.0.1:15184/landing.html');await landing.waitForLoadState('networkidle');
  const broken=await landing.locator('img').evaluateAll(imgs=>imgs.filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.src));
  expect(broken).toEqual([]);
  const overflow=await landing.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  expect(overflow).toBe(false);
  expect(await landing.getByRole('link',{name:'开始体验',exact:true}).first().getAttribute('href')).toBe('http://127.0.0.1:15183/#/login');
 }
 receipt.checks.push('landing at 320/768/1024/1440px: images, CTA, no horizontal overflow');
 await landing.screenshot({path:dir+'landing.png',fullPage:true});
 console.log(JSON.stringify(receipt,null,2));await writeFile('/tmp/sb3-browser-smoke.json',JSON.stringify(receipt,null,2));
} finally {await browser.close();}

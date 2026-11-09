import { describe, expect, it } from 'vitest';
import { detectInstallEnv } from './detectInstallEnv';

const ANDROID_CHROME =
  'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36';
const IOS_SAFARI =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1';
const WECHAT_ANDROID =
  'Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230901.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 MQQBrowser/6.2 TBS/046131 Mobile Safari/537.36 MMWEBID/1234 MicroMessenger/8.0.40';
const WECHAT_IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40(0x18002830) NetType/WIFI Language/zh_CN';
const DESKTOP =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

describe('detectInstallEnv', () => {
  it('已安装的 standalone 模式优先返回 standalone', () => {
    expect(
      detectInstallEnv({ userAgent: ANDROID_CHROME, standalone: true, hasBeforeInstallPrompt: false }),
    ).toBe('standalone');
  });

  it('微信安卓内置浏览器返回 wechat', () => {
    expect(
      detectInstallEnv({ userAgent: WECHAT_ANDROID, standalone: false, hasBeforeInstallPrompt: false }),
    ).toBe('wechat');
  });

  it('微信 iOS 内置浏览器也返回 wechat（微信优先于 iOS）', () => {
    expect(
      detectInstallEnv({ userAgent: WECHAT_IOS, standalone: false, hasBeforeInstallPrompt: false }),
    ).toBe('wechat');
  });

  it('微信环境优先于 beforeinstallprompt（微信里不触发安装）', () => {
    expect(
      detectInstallEnv({ userAgent: WECHAT_ANDROID, standalone: false, hasBeforeInstallPrompt: true }),
    ).toBe('wechat');
  });

  it('安卓 Chrome 捕获 beforeinstallprompt 返回 android', () => {
    expect(
      detectInstallEnv({ userAgent: ANDROID_CHROME, standalone: false, hasBeforeInstallPrompt: true }),
    ).toBe('android');
  });

  it('iOS Safari 无 beforeinstallprompt 返回 ios', () => {
    expect(
      detectInstallEnv({ userAgent: IOS_SAFARI, standalone: false, hasBeforeInstallPrompt: false }),
    ).toBe('ios');
  });

  it('桌面浏览器返回 unsupported', () => {
    expect(
      detectInstallEnv({ userAgent: DESKTOP, standalone: false, hasBeforeInstallPrompt: false }),
    ).toBe('unsupported');
  });

  it('安卓 Chrome 未捕获 beforeinstallprompt 也返回 android（仍可显示通用引导）', () => {
    expect(
      detectInstallEnv({ userAgent: ANDROID_CHROME, standalone: false, hasBeforeInstallPrompt: false }),
    ).toBe('android');
  });
});

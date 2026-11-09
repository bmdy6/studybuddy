/**
 * PWA 安装环境检测。
 *
 * 安装入口需要根据运行环境给出不同交互：
 * - 已安装（standalone）：不显示入口
 * - 微信内置浏览器：引导用户「在浏览器中打开」（微信屏蔽安装）
 * - iOS Safari：引导用户「分享 -> 添加到主屏幕」（不支持 beforeinstallprompt）
 * - 安卓 Chrome：可直接触发系统安装框
 * - 桌面/其他：不显示
 */

export type InstallEnv = 'standalone' | 'wechat' | 'android' | 'ios' | 'unsupported';

export interface DetectInstallEnvInput {
  userAgent: string;
  /** 是否处于 standalone（已安装全屏）模式。 */
  standalone: boolean;
  /** 是否已捕获 beforeinstallprompt 事件（安卓 Chrome 安装就绪）。 */
  hasBeforeInstallPrompt: boolean;
}

/**
 * 判定当前环境应如何呈现安装入口。优先级：
 * standalone > 微信 > iOS > 安卓 > 不支持。
 */
export function detectInstallEnv(input: DetectInstallEnvInput): InstallEnv {
  const { userAgent, standalone, hasBeforeInstallPrompt } = input;
  if (standalone) return 'standalone';
  if (/MicroMessenger/i.test(userAgent)) return 'wechat';
  if (/iPhone|iPad|iPod/i.test(userAgent)) return 'ios';
  if (/Android/i.test(userAgent) || hasBeforeInstallPrompt) return 'android';
  return 'unsupported';
}

/** 读取浏览器实际的安装环境参数（供组件调用）。 */
export function readInstallEnvFromBrowser(): DetectInstallEnvInput {
  const standalone =
    typeof window !== 'undefined' &&
    (window.matchMedia?.('(display-mode: standalone)').matches ||
      // iOS Safari 的 navigator.standalone
      (window.navigator as Navigator & { standalone?: boolean }).standalone === true);
  return {
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    standalone: Boolean(standalone),
    hasBeforeInstallPrompt: false,
  };
}

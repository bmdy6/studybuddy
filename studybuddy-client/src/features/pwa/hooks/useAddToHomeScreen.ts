/**
 * 「添加到主屏幕」安装入口逻辑 hook。
 *
 * 提供：环境检测、beforeinstallprompt 监听、触发安装/引导。
 * 由 AccountPage 用 AccountMenuItem 形式渲染入口，样式交给页面统一控制。
 */
import { useCallback, useEffect, useState } from 'react';
import {
  detectInstallEnv,
  readInstallEnvFromBrowser,
  type InstallEnv,
} from '../utils/detectInstallEnv';

/** beforeinstallprompt 事件类型（TS DOM lib 未内置）。 */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export interface AddToHomeScreenState {
  /** 是否显示入口（standalone/unsupported 不显示）。 */
  visible: boolean;
  env: InstallEnv;
  guideOpen: boolean;
  /** 点击入口：安卓已就绪则触发系统安装框，否则弹引导 Modal。 */
  trigger: () => Promise<void>;
  closeGuide: () => void;
}

export function useAddToHomeScreen(): AddToHomeScreenState {
  const [env, setEnv] = useState<InstallEnv>('unsupported');
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);

  useEffect(() => {
    setEnv(detectInstallEnv(readInstallEnvFromBrowser()));

    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
      setEnv((prev) => (prev === 'wechat' || prev === 'standalone' ? prev : 'android'));
    };
    const onAppInstalled = () => {
      setEnv('standalone');
      setDeferredPrompt(null);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt);
    window.addEventListener('appinstalled', onAppInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt);
      window.removeEventListener('appinstalled', onAppInstalled);
    };
  }, []);

  const trigger = useCallback(async () => {
    if (env === 'android' && deferredPrompt) {
      await deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (choice.outcome === 'accepted') {
        setEnv('standalone');
      }
      setDeferredPrompt(null);
      return;
    }
    // 微信 / iOS / 安卓未捕获 BIP：弹引导
    setGuideOpen(true);
  }, [env, deferredPrompt]);

  const visible = env !== 'standalone' && env !== 'unsupported';

  return {
    visible,
    env,
    guideOpen,
    trigger,
    closeGuide: () => setGuideOpen(false),
  };
}

/**
 * 响应式断点契约（PC 适配批次 1）。
 *
 * 全站统一断点，禁止各页面自行发明 767/768/769/1024：
 * - MOBILE：<768px —— 手机（底部导航、单列、任务 dock/Drawer）
 * - TABLET：768-1199px —— 紧凑桌面/平板（左侧窄导航、单主栏）
 * - DESKTOP：>=1200px —— 完整桌面（左侧导航 + 主内容 + 必要右栏）
 */

/** 桌面阅读正文列上限（聊天正文/长文本，避免横向过长） */
export const READING_COLUMN_MAX = 760;

/**
 * 统一断点 hook：基于 antd Grid.useBreakpoint 的语义化封装。
 * 返回当前设备形态，页面不再自己发明 768/1024 判断。
 */
import { Grid } from 'antd';

export function useBreakpoint() {
  const screens = Grid.useBreakpoint();
  return {
    isMobile: !screens.md, // <768
    isTablet: !!screens.md && !screens.xl, // 768-1199
    isDesktop: !!screens.xl, // >=1200
  };
}

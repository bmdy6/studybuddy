import type { ThemeConfig } from 'antd';
import { designColors, designShadows } from './designTokens';

export const appleTheme: ThemeConfig = {
  token: {
    colorPrimary: designColors.primary,
    colorSuccess: designColors.success,
    colorError: designColors.error,
    colorWarning: designColors.warning,
    colorBgLayout: designColors.bgLayout,
    colorText: designColors.text,
    colorTextSecondary: designColors.textSecondary,
    colorBorder: designColors.border,
    colorBorderSecondary: designColors.borderSecondary,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 16,
    borderRadius: 8,
    borderRadiusLG: 12,
    boxShadow: designShadows.card,
    boxShadowSecondary: designShadows.floating,
    padding: 16,
    paddingLG: 24,
    paddingXS: 8,
    margin: 16,
    marginLG: 24,
    marginXS: 8,
  },
  components: {
    Card: { borderRadiusLG: 12, paddingLG: 24 },
    Button: { borderRadius: 8, controlHeight: 40, fontWeight: 500 },
    Input: { borderRadius: 8, controlHeight: 40 },
    Layout: { bodyBg: designColors.bgLayout, siderBg: designColors.white },
    Tag: { borderRadiusSM: 6 },
  },
};
// agg-1

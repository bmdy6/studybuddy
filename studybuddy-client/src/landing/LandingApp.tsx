import { BRAND } from '@/shared/constants/brand';
import { HeroSection } from './sections/Hero';
import { ValueSection } from './sections/Value';
import { LoopSection } from './sections/Loop';
import { FeaturesSection } from './sections/Features';
import { StartSection } from './sections/Start';
import { TrustSection } from './sections/Trust';
import { FinalCtaSection } from './sections/FinalCta';

// 业务入口（登录/注册）：构建时经 VITE_APP_URL 注入，默认本机入口
const APP_URL = (import.meta.env.VITE_APP_URL as string | undefined)?.replace(/\/+$/, '') ?? 'http://127.0.0.1:5173';

export const loginUrl = `${APP_URL}/#/login`;

const NAV_LINKS = [
  { href: '#value', label: '为什么用' },
  { href: '#features', label: '能做什么' },
  { href: '#start', label: '如何开始' },
  { href: '#faq', label: '常见问题' },
];

export function LandingApp() {
  return (
    <div className="ld-page">
      <header className="ld-nav">
        <div className="ld-nav-inner">
          <a className="ld-brand" href="#top" aria-label={`${BRAND.name} 官网首页`}>
            <span className="ld-brand-mark" aria-hidden="true">
              {BRAND.name[0]}
            </span>
            <span className="ld-brand-name">{BRAND.name}</span>
          </a>
          <nav className="ld-nav-links" aria-label="页面导航">
            {NAV_LINKS.map((link) => (
              <a key={link.href} href={link.href}>
                {link.label}
              </a>
            ))}
          </nav>
          <a className="ld-btn ld-btn-primary ld-nav-cta" href={loginUrl}>
            开始体验
          </a>
        </div>
      </header>

      <main id="top">
        <HeroSection />
        <ValueSection />
        <LoopSection />
        <FeaturesSection />
        <StartSection />
        <TrustSection />
        <FinalCtaSection />
      </main>

      <footer className="ld-footer">
        <div className="ld-footer-inner">
          <span className="ld-footer-brand">{BRAND.name}</span>
          <span>面向家庭的轻量辅导工具 · 家长出题、孩子答题、AI 整理反馈</span>
          <span>© {new Date().getFullYear()} {BRAND.name}</span>
          <span>AGPL-3.0-only · 自托管</span>
        </div>
      </footer>
    </div>
  );
}

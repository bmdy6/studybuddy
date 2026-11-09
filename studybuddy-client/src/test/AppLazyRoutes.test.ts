import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const appSource = readFileSync(join(process.cwd(), 'src/app/router.tsx'), 'utf8');

describe('App route loading', () => {
  it('重页面通过 lazy import 加载，避免所有页面入口一起加载', () => {
    expect(appSource).toContain("const ProfilePage = lazy(() => import('@/features/family/pages/ProfilePage'))");
    expect(appSource).toContain("const ChatPage = lazy(() => import('@/features/chat/pages/ChatPage'))");
    expect(appSource).toContain(
      "const FamilyCompanionPage = lazy(() => import('@/features/family/pages/FamilyCompanionPage'))",
    );
    expect(appSource).not.toContain("import ProfilePage from '@/features/family/pages/ProfilePage'");
    expect(appSource).not.toContain("import ChatPage from '@/features/chat/pages/ChatPage'");
  });
});

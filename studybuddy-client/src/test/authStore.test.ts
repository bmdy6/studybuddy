import { beforeEach, describe, expect, it } from 'vitest';
import { useAuthStore } from '@/features/auth/store';

describe('authStore recent accounts', () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({
      token: null,
      role: null,
      displayName: null,
      avatar: null,
      userId: null,
      children: [],
      activeChildId: null,
      recentAccounts: [],
      authVersion: 0,
    });
  });

  it('缓存最近登录账号并支持无密码切换', () => {
    const store = useAuthStore.getState();

    store.login('teacher-token', 'parent', '哥哥', null, 1, [{ id: 2, display_name: '弟弟', mode: 'study' }], 'teacher');
    useAuthStore
      .getState()
      .login('student-token', 'student', '测试学生', null, 2, [], 'student');

    const afterLogin = useAuthStore.getState();
    expect(afterLogin.displayName).toBe('测试学生');
    expect(afterLogin.recentAccounts.map((item) => item.username)).toEqual(['student', 'teacher']);

    afterLogin.switchAccount('1');

    const afterSwitch = useAuthStore.getState();
    expect(afterSwitch.token).toBe('teacher-token');
    expect(afterSwitch.role).toBe('parent');
    expect(afterSwitch.displayName).toBe('哥哥');
    expect(afterSwitch.activeChildId).toBe(2);
  });

  it('可忘记某个最近账号', () => {
    useAuthStore.getState().login('student-token', 'student', '测试学生', null, 2, [], 'student');

    useAuthStore.getState().forgetAccount('2');

    expect(useAuthStore.getState().recentAccounts).toEqual([]);
  });

  it('登录、切换账号、切换孩子和退出都会更新身份版本', () => {
    const startVersion = useAuthStore.getState().authVersion;

    useAuthStore
      .getState()
      .login('teacher-token', 'parent', '哥哥', null, 1, [{ id: 2, display_name: '弟弟', mode: 'study' }], 'teacher');
    const afterParentLogin = useAuthStore.getState();
    expect(afterParentLogin.authVersion).toBeGreaterThan(startVersion);

    afterParentLogin.login('student-token', 'student', '测试学生', null, 2, [], 'student');
    const afterStudentLogin = useAuthStore.getState();
    expect(afterStudentLogin.authVersion).toBeGreaterThan(afterParentLogin.authVersion);

    afterStudentLogin.switchAccount('1');
    const afterSwitch = useAuthStore.getState();
    expect(afterSwitch.authVersion).toBeGreaterThan(afterStudentLogin.authVersion);

    afterSwitch.setActiveChild(2);
    const afterChild = useAuthStore.getState();
    expect(afterChild.authVersion).toBeGreaterThan(afterSwitch.authVersion);

    afterChild.logout();
    expect(useAuthStore.getState().authVersion).toBeGreaterThan(afterChild.authVersion);
  });
});

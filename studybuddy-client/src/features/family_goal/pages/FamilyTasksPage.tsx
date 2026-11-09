import { TeamOutlined } from '@ant-design/icons';

import StudentPageShell from '@/shared/components/StudentPageShell';
import TodayFamilyTasks from '@/features/family_goal/components/TodayFamilyTasks';
import { getActiveStudentId, useAuthStore } from '@/features/auth/store';
import { PageSpinner } from '@/shared/components/PageSpinner';

/**
 * 家庭任务页：孩子建目标 / 交作业 / 看驳回理由与累计奖励。
 * 入口在「我的」tab（2026-09-30 收敛：不再占今天页首屏）。
 */
export default function FamilyTasksPage() {
  const authState = useAuthStore();
  const studentId = getActiveStudentId(authState);

  return (
    <StudentPageShell
      title="家庭任务"
      subtitle="定个小目标，做完交照片给家长确认，攒奖励。"
      icon={<TeamOutlined />}
    >
      {studentId ? (
        <TodayFamilyTasks studentId={studentId} embedded />
      ) : (
        <PageSpinner />
      )}
    </StudentPageShell>
  );
}

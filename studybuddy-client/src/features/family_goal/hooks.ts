import { useEffect, useState } from 'react';
import { familyGoalApi } from '@/features/family_goal/api';
import type { FamilyTodayTask } from '@/types';

/** 待完成口径：还没交的（pending）+ 被驳回要重交的（rejected）。 */
const OPEN_TASK_STATUSES: readonly FamilyTodayTask['status'][] = ['pending', 'rejected'];

function countOpenTasks(tasks: FamilyTodayTask[]): number {
  return tasks.filter((task) => OPEN_TASK_STATUSES.includes(task.status)).length;
}

/** 今天待完成家庭任务数量：没有（0）就不提醒；studentId 缺失或请求失败保持 0，不打扰。 */
export function useOpenFamilyTaskCount(studentId: number | null | undefined): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!studentId) {
      setCount(0);
      return;
    }
    let alive = true;
    familyGoalApi
      .todayTasks(studentId)
      .then((tasks) => {
        if (alive) setCount(countOpenTasks(tasks));
      })
      .catch(() => {
        if (alive) setCount(0);
      });
    return () => {
      alive = false;
    };
  }, [studentId]);

  return count;
}

/**
 * 是否有家长审核账号绑定了该学生。
 * null = 还没查到（加载中或请求失败）：失败时宁可不提示，也不谎报“没绑”。
 */
export function useParentBound(studentId: number | null | undefined): boolean | null {
  const [parentBound, setParentBound] = useState<boolean | null>(null);

  useEffect(() => {
    if (!studentId) {
      setParentBound(null);
      return;
    }
    let alive = true;
    familyGoalApi
      .parentBound(studentId)
      .then((context) => {
        if (alive) setParentBound(context.parent_bound);
      })
      .catch(() => {
        if (alive) setParentBound(null);
      });
    return () => {
      alive = false;
    };
  }, [studentId]);

  return parentBound;
}

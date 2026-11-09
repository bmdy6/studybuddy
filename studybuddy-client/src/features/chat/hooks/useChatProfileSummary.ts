import { useEffect, useState } from 'react';
import { p2Api } from '@/features/p2/api';
import type { ProfileSummary } from '@/types';

export function useChatProfileSummary(token: string | null, studentId: number | null) {
  const [profileSummary, setProfileSummary] = useState<ProfileSummary | null>(null);

  useEffect(() => {
    if (!token || !studentId) {
      setProfileSummary(null);
      return;
    }
    let alive = true;
    p2Api
      .getProfileSummary(studentId)
      .then((summary) => {
        if (alive) setProfileSummary(summary);
      })
      .catch(() => {
        if (alive) setProfileSummary(null);
      });
    return () => {
      alive = false;
    };
  }, [studentId, token]);

  return profileSummary;
}

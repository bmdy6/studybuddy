import client from '@/shared/api/client';
import type {
  AttributeSnapshot,
  FeedbackItem,
  InterestItem,
  ProfileOnboardingRequest,
  ProfileSummary,
  RecommendationBoundary,
  RecommendationItem,
  StudyPlan,
  StudyPlanItem,
} from '@/types';

export const p2Api = {
  // 属性面板
  getAttributes: (studentId: number) =>
    client
      .get<{ current: AttributeSnapshot | null }>(`/api/students/${studentId}/attributes`)
      .then((r) => r.data),

  getAttributeHistory: (studentId: number) =>
    client
      .get<{ history: AttributeSnapshot[] }>(`/api/students/${studentId}/attributes?history=true`)
      .then((r) => r.data),

  initAttributes: (studentId: number, examScores: Record<string, number>) =>
    client
      .post<AttributeSnapshot>(`/api/students/${studentId}/attributes/init`, {
        exam_scores: examScores,
      })
      .then((r) => r.data),

  getProfileSummary: (studentId: number) =>
    client.get<ProfileSummary>(`/api/students/${studentId}/profile/summary`).then((r) => r.data),

  saveProfileOnboarding: (studentId: number, data: ProfileOnboardingRequest) =>
    client.post<ProfileSummary>(`/api/students/${studentId}/profile/onboarding`, data).then((r) => r.data),

  // 兴趣
  listInterests: (studentId: number) =>
    client.get<InterestItem[]>(`/api/students/${studentId}/interests`).then((r) => r.data),

  addInterest: (studentId: number, tag: string) =>
    client
      .post<InterestItem>(`/api/students/${studentId}/interests`, { tag, source: 'manual' })
      .then((r) => r.data),

  confirmInterest: (interestId: number) =>
    client.patch<InterestItem>(`/api/interests/${interestId}`, { approved: true }).then((r) => r.data),

  removeInterest: (interestId: number) =>
    client.delete(`/api/interests/${interestId}`).then((r) => r.data),

  // 学习计划
  listStudyPlans: (studentId: number, status: string | null = 'active') =>
    client
      .get<StudyPlan[]>(`/api/students/${studentId}/study-plans`, { params: { status } })
      .then((r) => r.data),

  createStudyPlan: (
    studentId: number,
    data: Pick<StudyPlan, 'title' | 'focus' | 'planned_date'> & {
      description?: string | null;
      context_refs?: Record<string, unknown> | null;
      items: Array<Pick<StudyPlanItem, 'title' | 'target' | 'minutes' | 'related_tags'>>;
    },
  ) => client.post<StudyPlan>(`/api/students/${studentId}/study-plans`, data).then((r) => r.data),

  updateStudyPlan: (
    planId: number,
    data: { title?: string; description?: string | null; planned_date?: string | null; revision: number },
  ) => client.patch<StudyPlan>(`/api/study-plans/${planId}`, data).then((r) => r.data),

  archiveStudyPlan: (planId: number) =>
    client.post<StudyPlan>(`/api/study-plans/${planId}/archive`).then((r) => r.data),

  carryOverStudyPlan: (planId: number) =>
    client.post<StudyPlan>(`/api/study-plans/${planId}/carry-over`).then((r) => r.data),

  updateStudyPlanItem: (itemId: number, status: 'todo' | 'done' | 'skipped', evidenceSummary?: string) =>
    client.patch<StudyPlanItem>(`/api/study-plan-items/${itemId}`, { status, evidence_summary: evidenceSummary }).then((r) => r.data),

  // 计划草案确认（学生点卡片"确认并创建"后调用，原子创建正式计划）
  confirmPlanDraft: (draftId: number, revision: number) =>
    client
      .post<{ plan_id: number }>(`/api/study-plan-drafts/${draftId}/confirm`, { revision })
      .then((r) => r.data),

  // 查草案详情（刷新后判断是否还需展示确认卡：已 created 的不恢复）
  getPlanDraft: (draftId: number, studentId?: number) =>
    client
      .get<{
        id: number;
        status: string;
        created_plan_id: number | null;
        revision: number;
        chat_session_id: number | null;
        created_at: string | null;
        is_expired: boolean;
        title: string;
        focus: string | null;
        planned_date: string | null;
        items: Array<{ title: string; target?: string | null; minutes: number; related_tags?: string[] }>;
        expires_at: string | null;
      }>(`/api/study-plan-drafts/${draftId}`, {
        params: studentId ? { student_id: studentId } : undefined,
      })
      .then((r) => r.data),

  // 反馈
  listFeedback: (studentId: number) =>
    client.get<FeedbackItem[]>(`/api/students/${studentId}/feedback`).then((r) => r.data),

  submitFeedback: (
    studentId: number,
    feedbackType: 'duration' | 'resource_view' | 'self_assess' | 'difficulty',
    content: string,
    relatedResourceId?: number,
  ) =>
    client
      .post<FeedbackItem>(`/api/students/${studentId}/feedback`, {
        feedback_type: feedbackType,
        content,
        related_resource_id: relatedResourceId,
      })
      .then((r) => r.data),

  // 推荐
  listRecommendations: (studentId: number) =>
    client
      .get<RecommendationItem[]>(`/api/students/${studentId}/recommendations`)
      .then((r) => r.data),

  getRecommendationBoundary: (studentId: number) =>
    client
      .get<RecommendationBoundary>(`/api/students/${studentId}/recommendation-boundary`)
      .then((r) => r.data),

  updateRecommendationBoundary: (studentId: number, data: Omit<RecommendationBoundary, 'student_id'>) =>
    client
      .put<RecommendationBoundary>(`/api/students/${studentId}/recommendation-boundary`, data)
      .then((r) => r.data),

  markClicked: (recId: number) =>
    client.post(`/api/recommendations/${recId}/click`).then((r) => r.data),
};

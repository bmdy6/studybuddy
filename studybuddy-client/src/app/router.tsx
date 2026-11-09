import { WECHAT_ENABLED } from '@/shared/constants';
import { Suspense, lazy } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import MainLayout from '@/app/layouts/MainLayout';
import ProtectedRoute from '@/features/auth/ProtectedRoute';
import RoleRedirect from '@/features/auth/RoleRedirect';

// 页面懒加载。后续 feature 迁移时，import 路径从 @/pages/xxx -> @/features/<域>/pages/xxx。
const LoginPage = lazy(() => import('@/features/auth/pages/LoginPage'));
const WechatParentBindPage = lazy(() => import('@/features/wechat/pages/WechatParentBindPage'));
const ChatPage = lazy(() => import('@/features/chat/pages/ChatPage'));
const ProfilePage = lazy(() => import('@/features/family/pages/ProfilePage'));
const StudyPlansPage = lazy(() => import('@/features/learning/pages/StudyPlansPage'));
const LearnHomePage = lazy(() => import('@/features/learning/pages/LearnHomePage'));
const LearnSearchPage = lazy(() => import('@/features/learning/pages/LearnSearchPage'));
const GrowthHomePage = lazy(() => import('@/features/growth/pages/GrowthHomePage'));
const AccountPage = lazy(() => import('@/features/family/pages/AccountPage'));
const StudentsPage = lazy(() => import('@/features/family/pages/StudentsPage'));
const StudentDetailPage = lazy(() => import('@/features/family/pages/StudentDetailPage'));
const ExamListPage = lazy(() => import('@/features/exams/pages/ExamListPage'));
const ExamTakingPage = lazy(() => import('@/features/exams/pages/ExamTakingPage'));
const ExamResultPage = lazy(() => import('@/features/exams/pages/ExamResultPage'));
const ExamPreviewPage = lazy(() => import('@/features/exams/pages/ExamPreviewPage'));
const ErrorBookPage = lazy(() => import('@/features/error_book/pages/ErrorBookPage'));
const DiagnosisPage = lazy(() => import('@/features/learning/pages/DiagnosisPage'));
const LearningMapPage = lazy(() => import('@/features/learning/pages/LearningMapPage'));
const MaterialsPage = lazy(() => import('@/features/materials/pages/MaterialsPage'));
const NotesPage = lazy(() => import('@/features/note/pages/NotesPage'));
const NoteDetailPage = lazy(() => import('@/features/note/pages/NoteDetailPage'));
const DailyReviewPage = lazy(() => import('@/features/growth/pages/DailyReviewPage'));
const DailyRecordsPage = lazy(() => import('@/features/growth/pages/DailyRecordsPage'));
const HelpPage = lazy(() => import('@/app/pages/HelpPage'));
const FamilyCompanionPage = lazy(() => import('@/features/family/pages/FamilyCompanionPage'));
const FamilyTasksPage = lazy(() => import('@/features/family_goal/pages/FamilyTasksPage'));
const DashboardPage = lazy(() => import('@/features/teacher/pages/DashboardPage'));
const GradingPage = lazy(() => import('@/features/teacher/pages/GradingPage'));
const ExamManagePage = lazy(() => import('@/features/teacher/pages/ExamManagePage'));
const QuestionBankPage = lazy(() => import('@/features/teacher/pages/QuestionBankPage'));

function RouteFallback() {
  return (
    <div style={{ padding: 80, textAlign: 'center' }}>
      <Spin />
    </div>
  );
}

export default function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        {/* 公开路由 */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/wechat-parent-bind" element={<>{WECHAT_ENABLED ? <WechatParentBindPage /> : <Navigate to="/login" replace />}</>} />

        {/* 答题页：全屏，不在 MainLayout 内 */}
        <Route
          path="/exams/:examId/take"
          element={
            <ProtectedRoute>
              <ExamTakingPage />
            </ProtectedRoute>
          }
        />

        {/* 受保护路由 -- 由 MainLayout 提供侧栏 + 内容区 */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          }
        >
          {/* 根据角色跳转 */}
          <Route index element={<RoleRedirect />} />

          {/* Agent 对话首页（P2，默认首页） */}
          <Route path="chat" element={<ChatPage />} />
          <Route path="study-plans" element={<LearnHomePage />} />
          <Route path="search" element={<LearnSearchPage />} />
          <Route path="study-plans/all" element={<StudyPlansPage />} />
          <Route path="growth" element={<GrowthHomePage />} />
          <Route path="profile" element={<ProfilePage />} />
          {/* 个人中心（账户设置）：显示名/头像/密码，UX P0-1 */}
          <Route path="account" element={<AccountPage />} />
          <Route
            path="students"
            element={
              <ProtectedRoute role="parent">
                <StudentsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="students/:id"
            element={
              <ProtectedRoute role="parent">
                <StudentDetailPage />
              </ProtectedRoute>
            }
          />

          {/* 学生页面 */}
          <Route path="exams" element={<ExamListPage />} />
          <Route path="exams/:examId/result" element={<ExamResultPage />} />
          {/* 试卷只读预览（parent 试卷管理页「预览」入口，问题5：不走答题 take 流程） */}
          <Route path="exams/:examId/preview" element={<ExamPreviewPage />} />
          <Route path="error-book" element={<ErrorBookPage />} />
          <Route path="diagnosis" element={<DiagnosisPage />} />
          <Route path="learning-map" element={<LearningMapPage />} />
          <Route path="materials" element={<MaterialsPage />} />
          <Route
            path="daily-review"
            element={
              <ProtectedRoute role="student">
                <DailyReviewPage />
              </ProtectedRoute>
            }
          />
          <Route path="daily-records" element={<DailyRecordsPage />} />
          {/* 笔记：列表（含盲区聚合）+ 详情 */}
          <Route path="notes" element={<NotesPage />} />
          <Route path="notes/:noteId" element={<NoteDetailPage />} />
          <Route path="help" element={<HelpPage />} />
          <Route
            path="family"
            element={
              <ProtectedRoute role="student">
                <>{WECHAT_ENABLED ? <FamilyCompanionPage /> : <Navigate to="/account" replace />}</>
              </ProtectedRoute>
            }
          />
          {/* 家庭任务：入口收敛到「我的」tab（2026-09-30），不再占今天页 */}
          <Route
            path="family-tasks"
            element={
              <ProtectedRoute role="student">
                <FamilyTasksPage />
              </ProtectedRoute>
            }
          />

          {/* 管理页面（parent 专用，阶段一复用原 teacher 页面组件） */}
          <Route
            path="teacher/dashboard"
            element={
              <ProtectedRoute role="parent">
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="teacher/grading"
            element={
              <ProtectedRoute role="parent">
                <GradingPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="teacher/exams"
            element={
              <ProtectedRoute role="parent">
                <ExamManagePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="teacher/question-bank"
            element={
              <ProtectedRoute role="parent">
                <QuestionBankPage />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

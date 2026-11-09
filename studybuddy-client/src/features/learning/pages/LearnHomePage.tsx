/**
 * 学习首页（Stitch 6_10 screen 9）。
 *
 * 聚合学习内容入口：搜索栏 + 继续学习 + 分类网格。
 * 底部导航"学习"tab 落地页，替代直接进 StudyPlansPage。
 */

import { useCallback, useEffect, useState } from 'react';
import { Button, Skeleton, Typography } from 'antd';
import {
  BookOutlined,
  CalendarOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
  ReadOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/features/auth/store';
import { learningFlowApi } from '@/features/learning/learningFlow';
import { ROLES } from '@/shared/constants';
import type { LearningFlowEntry } from '@/types';

const { Text } = Typography;

interface CategoryItem {
  label: string;
  desc: string;
  icon: React.ReactNode;
  path: string;
  accent: string;
}

const categories: CategoryItem[] = [
  {
    label: '错题',
    desc: '按学科和题型复习',
    icon: <FileSearchOutlined />,
    path: '/error-book',
    accent: 'error',
  },
  {
    label: '知识地图',
    desc: '按知识点聚合学习内容',
    icon: <NodeIndexOutlined />,
    path: '/learning-map',
    accent: 'primary',
  },
  {
    label: '试卷',
    desc: '练习与考试记录',
    icon: <FileTextOutlined />,
    path: '/exams',
    accent: 'neutral',
  },
  {
    label: '笔记',
    desc: '学习记录与盲区',
    icon: <BookOutlined />,
    path: '/notes',
    accent: 'gold',
  },
  {
    label: '素材',
    desc: '上传的课本与资料',
    icon: <FolderOpenOutlined />,
    path: '/materials',
    accent: 'neutral',
  },
  {
    label: '每日记录',
    desc: '查看每天的学习事实',
    icon: <CalendarOutlined />,
    path: '/daily-records',
    accent: 'primary',
  },
];

// 学科专属入口（兴趣模式隐藏：错题/知识地图/试卷是学科体系，兴趣不展示）
const HOBBY_HIDDEN_PATHS = ['/error-book', '/learning-map', '/exams'];

export default function LearnHomePage() {
  const navigate = useNavigate();
  const authStore = useAuthStore();
  // 入口显隐按目标学生模式（家长按 activeChild 的 mode，学生按自己）
  const effectiveMode =
    authStore.role === 'parent' && authStore.activeChildId
      ? (authStore.children.find((c) => c.id === authStore.activeChildId)?.mode ?? 'study')
      : authStore.mode;
  const hobbyMode = effectiveMode === 'hobby';
  const authState = useAuthStore();
  const { role, userId, activeChildId } = authState;
  const studentId = role === ROLES.STUDENT ? userId : activeChildId;
  const [entry, setEntry] = useState<LearningFlowEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const loadEntry = useCallback(async () => {
    if (!studentId) {
      setEntry(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      setEntry(await learningFlowApi.getEntry(studentId));
    } catch {
      setEntry(null);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    void loadEntry();
  }, [loadEntry]);

  const handleContinue = () => {
    // 学习计划场景：直接进 task session（与 TodayPlanPanel 顶部「继续学习」同一入口），
    // 不再把指令预填到主会话。后端 entry 带 item_id 时由 ChatPage 自动建/恢复 task session。
    if (entry?.kind === 'continue_plan' && entry.item_id) {
      navigate(`/chat?continue_task_item=${entry.item_id}`);
      return;
    }
    if (entry?.prompt) {
      navigate(`/chat?prompt=${encodeURIComponent(entry.prompt)}`);
    } else {
      navigate('/chat');
    }
  };

  return (
    <div className="sb-learn-home">
      {/* 标题区：与其他学习页 StudentPageShell hero 视觉一致（F3 收口） */}
      <section className="sb-student-hero">
        <div className="sb-student-hero-main">
          <div className="sb-student-hero-icon"><ReadOutlined /></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="sb-student-hero-title">学习</span>
            <span className="sb-student-hero-subtitle">错题、知识地图、试卷、笔记、素材和每日记录</span>
          </div>
        </div>
      </section>

      {/* 搜索栏 */}
      <button
        type="button"
        className="sb-learn-search"
        aria-label="搜索学习内容"
        onClick={() => navigate('/search')}
      >
        <SearchOutlined />
        <span className="sb-learn-search-placeholder">搜索学科、题目、知识点…</span>
      </button>

      {/* parent 未选孩子提示 */}
      {role === ROLES.PARENT && !studentId && (
        <div className="sb-learn-empty-hint">
          <Text type="secondary">请先选择一个学生</Text>
        </div>
      )}

      {/* 错误态 */}
      {error && (
        <div className="sb-learn-empty-hint">
          <Text type="secondary">暂时没拿到学习建议</Text>
          <Button
            type="text"
            icon={<ReloadOutlined />}
            aria-label="重新加载"
            onClick={() => void loadEntry()}
          >
            重新加载
          </Button>
        </div>
      )}

      {/* 继续学习 */}
      <section className="sb-learn-continue">
        <div className="sb-learn-section-heading">
          <Text className="sb-learn-section-title">继续学习</Text>
          <Button type="link" size="small" onClick={() => navigate('/study-plans/all')}>
            管理计划
          </Button>
        </div>
        {loading ? (
          <div className="sb-learn-continue-card sb-learn-continue-card--loading">
            <Skeleton active paragraph={{ rows: 1 }} title={{ width: '60%' }} />
          </div>
        ) : entry && entry.kind !== 'empty' ? (
          <button
            type="button"
            className="sb-learn-continue-card"
            onClick={handleContinue}
            aria-label={`继续学习 ${entry.title}`}
          >
            <div className="sb-learn-continue-body">
              <Text className="sb-learn-continue-tag">{entry.source_type === 'study_plan' ? '学习计划' : '错题复习'}</Text>
              <Text className="sb-learn-continue-title">{entry.title}</Text>
              <Text className="sb-learn-continue-desc">{entry.description}</Text>
            </div>
            <span className="sb-learn-continue-play">
              <PlayCircleOutlined />
            </span>
          </button>
        ) : (
          <button
            type="button"
            className="sb-learn-continue-card sb-learn-continue-card--empty"
            onClick={() => navigate('/chat')}
          >
            <div className="sb-learn-continue-body">
              <Text className="sb-learn-continue-title">告诉助手今天想学什么</Text>
              <Text className="sb-learn-continue-desc">AI 会帮你安排学习计划</Text>
            </div>
            <span className="sb-learn-continue-play">
              <PlayCircleOutlined />
            </span>
          </button>
        )}
      </section>

      {/* 分类入口 */}
      <section className="sb-learn-categories">
        <Text className="sb-learn-section-title">学习内容</Text>
        <div className="sb-learn-category-grid">
          {(hobbyMode ? categories.filter((c) => !HOBBY_HIDDEN_PATHS.includes(c.path)) : categories).map((cat) => (
            <button
              type="button"
              key={cat.path}
              className={`sb-learn-category-item sb-learn-category-item--${cat.accent}`}
              onClick={() => navigate(cat.path)}
              aria-label={cat.label}
            >
              <span className="sb-learn-category-icon">{cat.icon}</span>
              <span className="sb-learn-category-label">{cat.label}</span>
              <span className="sb-learn-category-desc">{cat.desc}</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

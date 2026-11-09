/**
 * 成长首页（成长栏落地页）。
 *
 * 成长首页只做两件事：呈现连续性学习进度（全站独有），以及引导到两个详情页
 * （学情诊断 / 学习档案）。薄弱知识点列表、能力雷达与成长曲线在各自详情页里，
 * 这里只在入口卡上给一句计数摘要，避免和详情页内容重复。
 */

import { useCallback, useEffect, useState } from 'react';
import { Button, Empty, Skeleton, Typography } from 'antd';
import { BarChartOutlined, TrophyOutlined, RightOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { learningMapApi } from '@/features/learning/learningMap';
import { p2Api } from '@/features/p2/api';
import { learningProgressApi } from '@/features/learning/learningProgress';
import { useAuthStore } from '@/features/auth/store';
import { ROLES } from '@/shared/constants';
import type {
  DayProgress,
  LearningMapResponse,
  AttributeSnapshot,
  LearningProgressMetrics,
} from '@/types';

const { Text } = Typography;

const TREND_SUBJECTS = [
  { key: 'chinese', label: '语文' },
  { key: 'math', label: '数学' },
  { key: 'english', label: '英语' },
] as const;

export default function GrowthHomePage() {
  const navigate = useNavigate();
  const authState = useAuthStore();
  const { role, userId, activeChildId } = authState;
  const studentId = role === ROLES.STUDENT ? userId : activeChildId;

  const [mapData, setMapData] = useState<LearningMapResponse | null>(null);
  const [history, setHistory] = useState<AttributeSnapshot[]>([]);
  const [progress, setProgress] = useState<LearningProgressMetrics | null>(null);
  const [progressError, setProgressError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    if (!studentId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const [map, attr, progressData] = await Promise.all([
        learningMapApi.get(studentId),
        p2Api.getAttributeHistory(studentId).catch(() => ({ history: [] })),
        learningProgressApi
          .get(studentId)
          .then((data) => ({ data, error: false as const }))
          .catch(() => ({ data: null, error: true as const })),
      ]);
      setMapData(map);
      setHistory(attr.history ?? []);
      setProgress(progressData.data);
      setProgressError(progressData.error);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  // 待巩固的知识点数 + 前 2 个最值得提醒的（完整列表见学情诊断页）。
  const weakCount = (mapData?.summary.weak ?? 0) + (mapData?.summary.reviewing ?? 0);
  const focusNodes = (mapData?.nodes ?? [])
    .filter((n) => n.status === 'weak' || n.status === 'reviewing')
    .slice(0, 2);

  // 最近一次有证据的能力变化里，幅度最大的那科一句话（完整曲线见学习档案页）。
  function latestAbilityChange(): string | null {
    if (history.length < 2) return null;
    const latest = history[history.length - 1];
    const prev = history[history.length - 2];
    let best: { label: string; delta: number } | null = null;
    for (const subject of TREND_SUBJECTS) {
      if (!latest.snapshot.subject_sources?.[subject.key]) continue;
      const latestValue = latest.snapshot[subject.key];
      const prevValue = prev.snapshot[subject.key];
      if (latestValue == null || prevValue == null || latestValue === prevValue) continue;
      const delta = latestValue - prevValue;
      if (!best || Math.abs(delta) > Math.abs(best.delta)) {
        best = { label: subject.label, delta };
      }
    }
    if (!best) return null;
    return best.delta > 0 ? `${best.label}上升 ${best.delta}` : `${best.label}下降 ${-best.delta}`;
  }
  const abilityChange = latestAbilityChange();

  function dayLabel(day: DayProgress) {
    const date = new Date(`${day.record_date}T00:00:00`);
    return `${date.getMonth() + 1}月${date.getDate()}日`;
  }

  const hasRealProgress = Boolean(
    progress &&
    (progress.streak_days > 0 ||
      progress.today.total_count > 0 ||
      progress.week.some((day) => day.status === 'active')),
  );

  if (loading) {
    return (
      <div className="sb-growth-home">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }

  if (!studentId) {
    return (
      <div className="sb-growth-home">
        <Empty description="请先选择一个学生" style={{ marginTop: 60 }} />
      </div>
    );
  }

  return (
    <div className="sb-growth-home">
      {/* 真实学习进度：连续天数为主，今日与近 7 天为辅，本周状态条做轻图表 */}
      <section className="sb-growth-section" aria-label="真实学习进度">
        <Text className="sb-growth-section-title">真实学习进度</Text>
        {progressError ? (
          <div className="sb-growth-focus-empty">
            <Text type="secondary">真实进度暂时加载失败，其他成长数据仍可查看</Text>
            <Button type="text" icon={<ReloadOutlined />} onClick={() => void load()}>
              重新加载进度
            </Button>
          </div>
        ) : !progress || !hasRealProgress ? (
          <div className="sb-growth-focus-empty">
            <Text type="secondary">记录还少，完成学习后会显示连续天数和本周状态</Text>
          </div>
        ) : (
          <>
            <div className="sb-growth-hero">
              <strong className="sb-growth-hero-streak">{progress.streak_days} 天</strong>
              <span className="sb-growth-hero-label">连续学习</span>
            </div>
            <div className="sb-growth-hero-sub">
              <span>
                今日{' '}
                <strong>
                  {progress.today.total_count
                    ? `${progress.today.completed_count}/${progress.today.total_count}`
                    : '暂无计划'}
                </strong>
                {progress.today.completion_rate != null && (
                  <small>· {Math.round(progress.today.completion_rate * 100)}%</small>
                )}
              </span>
              <span>
                近 7 天 <strong>{progress.recent_7_days_completed_tasks} 项</strong>
              </span>
            </div>
            {progress.week.length > 0 && (
              <div className="sb-growth-week" aria-label="本周学习状态">
                {progress.week.map((day) => (
                  <div
                    key={day.record_date}
                    className={`sb-growth-week-day sb-growth-week-day--${day.status}`}
                    title={`${dayLabel(day)}：${day.completed_count} 项`}
                  >
                    <span>{dayLabel(day)}</span>
                    <i aria-hidden="true" />
                    <small>
                      {day.status === 'future'
                        ? '未到'
                        : day.status === 'no_plan'
                          ? '无记录'
                          : day.status === 'planned'
                            ? '计划'
                            : `${day.completed_count} 项`}
                    </small>
                  </div>
                ))}
              </div>
            )}
            <Text type="secondary" className="sb-growth-progress-source">
              来源：每日学习记录的真实证据，不含预计时长和无证据分数
            </Text>
          </>
        )}
      </section>

      {/* 成长工具：两个详情页入口，描述带一句计数摘要；手机端去这两个页面的唯一通道 */}
      <section className="sb-growth-section">
        <Text className="sb-growth-section-title">成长工具</Text>
        <div className="sb-growth-entries">
          <button
            type="button"
            className="sb-growth-entry"
            onClick={() => navigate('/diagnosis')}
            aria-label="学情诊断"
          >
            <span className="sb-growth-entry-icon sb-growth-entry-icon--primary">
              <BarChartOutlined />
            </span>
            <span className="sb-growth-entry-body">
              <span className="sb-growth-entry-title">学情诊断</span>
              <span className="sb-growth-entry-desc">
                {error
                  ? '暂时没拿到学习数据'
                  : weakCount === 0
                    ? '暂无薄弱点，继续保持'
                    : `${weakCount} 个知识点待巩固`}
              </span>
              {focusNodes.length > 0 && (
                <span className="sb-growth-entry-weak-list">
                  {focusNodes.map((node) => (
                    <span key={node.tag} className="sb-growth-entry-weak-item">
                      <span className="sb-growth-entry-weak-tag">{node.tag}</span>
                      <i>错 {node.error_count} 次</i>
                    </span>
                  ))}
                </span>
              )}
            </span>
            <RightOutlined className="sb-growth-entry-arrow" />
          </button>
          <button
            type="button"
            className="sb-growth-entry"
            onClick={() => navigate('/profile')}
            aria-label="学习档案"
          >
            <span className="sb-growth-entry-icon sb-growth-entry-icon--gold">
              <TrophyOutlined />
            </span>
            <span className="sb-growth-entry-body">
              <span className="sb-growth-entry-title">学习档案</span>
              <span className="sb-growth-entry-desc">{abilityChange ?? '能力数据待补充'}</span>
            </span>
            <RightOutlined className="sb-growth-entry-arrow" />
          </button>
        </div>
        {error && (
          <div className="sb-growth-empty-hint">
            <Button type="text" icon={<ReloadOutlined />} onClick={() => void load()}>
              重新加载
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

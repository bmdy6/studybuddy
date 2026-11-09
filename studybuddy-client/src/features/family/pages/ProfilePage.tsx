/**
 * 个人属性面板页（P2.1 F5）。
 *
 * 个人属性面板：雷达图 + 属性条 + 兴趣标签 + 历史成长曲线。
 * 配色（调研方案）：属性条静止低饱和蓝灰 var(--sb-color-attr-neutral)，涨分绿 var(--sb-color-success-strong)，成就金 var(--sb-color-gold)。
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Card,
  Typography,
  Tag,
  Input,
  Button,
  Checkbox,
  Empty,
  InputNumber,
  Spin,
  Select,
  Tooltip,
  message,
  Row,
  Col,
  Space,
} from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  CheckOutlined,
  CloseOutlined,
  PlusOutlined,
  RadarChartOutlined,
  TrophyOutlined,
  HeartOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import StudentPageShell from '@/shared/components/StudentPageShell';
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as ChartTooltip,
  Legend,
} from 'recharts';
import { p2Api } from '@/features/p2/api';
import { useAuthStore } from '@/features/auth/store';
import type {
  AttributeSnapshot,
  AttributeSubjectSource,
  InterestItem,
  ProfileSummary,
  RecommendationBoundary,
} from '@/types';

const { Text } = Typography;

/** 能力项配置：key 对应 snapshot 字段，label 用于展示，tip 描述含义。 */
const ATTRIBUTE_SUBJECTS = [
  { key: 'chinese', label: '语文', tip: '语文科目的最近大考折算分（满分100）' },
  { key: 'math', label: '数学', tip: '数学科目的最近大考折算分（满分100）' },
  { key: 'english', label: '英语', tip: '英语科目的最近大考折算分（满分100）' },
  { key: 'pe', label: '体育', tip: '体育成绩折算分（满分100）' },
  { key: 'engagement', label: '学习投入度', tip: '综合学习时长、任务完成度、互动频率的估算值，越高越积极' },
] as const;

const SOURCE_LABELS: Record<AttributeSubjectSource, string> = {
  exam_score: '大考成绩',
  manual_adjust: '助教微调',
};

export default function ProfilePage() {
  const { role, activeChildId, userId } = useAuthStore();
  const studentId = role === 'parent' ? activeChildId : userId;
  const [attrs, setAttrs] = useState<AttributeSnapshot | null>(null);
  const [history, setHistory] = useState<AttributeSnapshot[]>([]);
  const [interests, setInterests] = useState<InterestItem[]>([]);
  const [profileSummary, setProfileSummary] = useState<ProfileSummary | null>(null);
  const [recommendationBoundary, setRecommendationBoundary] = useState<RecommendationBoundary | null>(null);
  const [coreLoading, setCoreLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [interestsLoading, setInterestsLoading] = useState(false);
  const [boundaryLoading, setBoundaryLoading] = useState(false);
  const [newInterest, setNewInterest] = useState('');
  const [updatingInterestIds, setUpdatingInterestIds] = useState<Set<number>>(new Set());
  const [savingBoundary, setSavingBoundary] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const [savingOnboarding, setSavingOnboarding] = useState(false);
  const [onboardingForm, setOnboardingForm] = useState({
    grade: '',
    semester: '',
    school: '',
    district: '',
    weakSubjects: '',
    interests: '',
    preferredTime: '',
    sessionMinutes: 25,
  });

  const applyProfileSummary = useCallback((summary: ProfileSummary) => {
    setProfileSummary(summary);
    setOnboardingForm((current) => ({
      ...current,
      grade: summary.summary.grade ?? current.grade,
      semester: summary.summary.semester ?? current.semester,
      school: summary.summary.school ?? current.school,
      district: summary.summary.district ?? current.district,
      weakSubjects: (summary.summary.weak_subjects ?? []).join('、') || current.weakSubjects,
      interests: (summary.summary.interests ?? []).join('、') || current.interests,
      preferredTime:
        typeof summary.summary.study_preferences?.preferred_time === 'string'
          ? summary.summary.study_preferences.preferred_time
          : current.preferredTime,
      sessionMinutes:
        typeof summary.summary.study_preferences?.session_minutes === 'number'
          ? summary.summary.study_preferences.session_minutes
          : current.sessionMinutes,
    }));
  }, []);

  const loadCore = useCallback(async () => {
    if (!studentId) {
      setAttrs(null);
      setProfileSummary(null);
      setCoreLoading(false);
      return;
    }
    setCoreLoading(true);
    try {
      const [attrResult, summaryResult] = await Promise.allSettled([
        p2Api.getAttributes(studentId),
        p2Api.getProfileSummary(studentId),
      ]);

      setAttrs(attrResult.status === 'fulfilled' ? attrResult.value.current : null);
      if (summaryResult.status === 'fulfilled') {
        applyProfileSummary(summaryResult.value);
      }
    } catch {
      // 忽略，未初始化时 current 为 null
    } finally {
      setCoreLoading(false);
    }
  }, [applyProfileSummary, studentId]);

  const loadHistory = useCallback(async () => {
    if (!studentId) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    try {
      const data = await p2Api.getAttributeHistory(studentId);
      setHistory(data.history);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [studentId]);

  const loadInterests = useCallback(async () => {
    if (!studentId) {
      setInterests([]);
      return;
    }
    setInterestsLoading(true);
    try {
      setInterests(await p2Api.listInterests(studentId));
    } catch {
      setInterests([]);
    } finally {
      setInterestsLoading(false);
    }
  }, [studentId]);

  const loadBoundary = useCallback(async () => {
    if (role !== 'parent' || !studentId) {
      setRecommendationBoundary(null);
      return;
    }
    setBoundaryLoading(true);
    try {
      setRecommendationBoundary(await p2Api.getRecommendationBoundary(studentId));
    } catch {
      setRecommendationBoundary(null);
    } finally {
      setBoundaryLoading(false);
    }
  }, [role, studentId]);

  useEffect(() => {
    void (async () => {
      await loadCore();
      void Promise.all([loadHistory(), loadInterests(), loadBoundary()]);
    })();
  }, [loadBoundary, loadCore, loadHistory, loadInterests]);

  const handleAddInterest = async () => {
    if (!studentId) return;
    if (!newInterest.trim()) return;
    try {
      await p2Api.addInterest(studentId, newInterest.trim());
      setNewInterest('');
      void loadInterests();
      message.success(role === 'parent' ? '兴趣建议已提交，等待学生确认' : '兴趣已添加');
    } catch {
      message.error('添加失败');
    }
  };

  const parseList = (value: string) =>
    value
      .split(/[、,，\s]+/)
      .map((item) => item.trim())
      .filter(Boolean);

  const saveOnboarding = async () => {
    if (!studentId) return;
    setSavingOnboarding(true);
    try {
      const saved = await p2Api.saveProfileOnboarding(studentId, {
        grade: onboardingForm.grade,
        semester: onboardingForm.semester,
        school: onboardingForm.school,
        district: onboardingForm.district,
        weak_subjects: parseList(onboardingForm.weakSubjects),
        interests: parseList(onboardingForm.interests),
        study_preferences: {
          preferred_time: onboardingForm.preferredTime,
          session_minutes: onboardingForm.sessionMinutes,
        },
      });
      applyProfileSummary(saved);
      setOnboardingOpen(false);
      setOnboardingDismissed(false);
      await Promise.all([loadCore(), loadInterests()]);
      message.success('学习画像已保存');
    } catch {
      message.error('保存画像失败');
    } finally {
      setSavingOnboarding(false);
    }
  };

  const updateInterest = async (interestId: number, action: 'confirm' | 'remove') => {
    setUpdatingInterestIds((ids) => new Set(ids).add(interestId));
    try {
      if (action === 'confirm') {
        await p2Api.confirmInterest(interestId);
        message.success('兴趣已确认');
      } else {
        await p2Api.removeInterest(interestId);
        message.success('兴趣已移除');
      }
      await loadInterests();
    } catch {
      message.error(action === 'confirm' ? '确认失败' : '移除失败');
    } finally {
      setUpdatingInterestIds((ids) => {
        const next = new Set(ids);
        next.delete(interestId);
        return next;
      });
    }
  };

  const updateBoundaryDraft = (patch: Partial<RecommendationBoundary>) => {
    setRecommendationBoundary((current) => {
      if (!studentId) return current;
      const base = current ?? {
        student_id: studentId,
        allowed_platforms: ['bilibili'],
        blocked_keywords: [],
        daily_limit: 3,
        allow_entertainment_interests: false,
      };
      return { ...base, ...patch };
    });
  };

  const saveRecommendationBoundary = async () => {
    if (!recommendationBoundary || !studentId) return;
    setSavingBoundary(true);
    try {
      const saved = await p2Api.updateRecommendationBoundary(studentId, {
        allowed_platforms: recommendationBoundary.allowed_platforms,
        blocked_keywords: recommendationBoundary.blocked_keywords,
        daily_limit: recommendationBoundary.daily_limit,
        allow_entertainment_interests: recommendationBoundary.allow_entertainment_interests,
      });
      setRecommendationBoundary(saved);
      message.success('推荐边界已保存');
    } catch {
      message.error('保存推荐边界失败');
    } finally {
      setSavingBoundary(false);
    }
  };

  if (coreLoading) {
    return (
      <StudentPageShell title="学习档案" icon={<TrophyOutlined />} maxWidth={1000}>
        <PageSpinner padding={60} />
      </StudentPageShell>
    );
  }

  if (!studentId) {
    return (
      <StudentPageShell title="学习档案" icon={<TrophyOutlined />} maxWidth={1000}>
        <Card>
          <Empty description={role === 'parent' ? '请先选择要查看的学生' : '暂时无法读取学习档案'} />
        </Card>
      </StudentPageShell>
    );
  }

  const snapshot = attrs?.snapshot;
  const sources = snapshot?.subject_sources ?? {};

  // 判断某能力项是否有真实证据（大考录入或助教微调）
  const hasEvidence = (
    key: 'chinese' | 'math' | 'english' | 'pe' | 'engagement',
  ): boolean => Boolean(sources[key]);

  // 雷达图：只画有证据的科目；无证据科目不绘制假分
  const radarData = snapshot
    ? ATTRIBUTE_SUBJECTS.map((s) => ({
        subject: s.label,
        value: hasEvidence(s.key) ? snapshot[s.key] ?? null : null,
        fullMark: 100,
      }))
    : [];
  const radarHasData = radarData.some((d) => d.value !== null);

  // 成长曲线数据：无证据科目的快照值不参与趋势（避免假 60 干扰曲线）
  const lineData = history.map((h, i) => ({
    name: `#${i + 1}`,
    语文: h.snapshot.subject_sources?.chinese ? h.snapshot.chinese : null,
    数学: h.snapshot.subject_sources?.math ? h.snapshot.math : null,
    英语: h.snapshot.subject_sources?.english ? h.snapshot.english : null,
  }));

  return (
    <StudentPageShell
      title="学习档案"
      subtitle="能力雷达、成长曲线与兴趣"
      icon={<TrophyOutlined />}
      maxWidth={1000}
    >
      {profileSummary?.needs_onboarding && !onboardingDismissed && (
        <Card
          title="学习画像待补全"
          variant="borderless"
          style={{ marginBottom: 16, border: '1px solid var(--sb-color-border-warm)' }}
          extra={
            <Space>
              <Button type="primary" onClick={() => setOnboardingOpen(true)}>
                补全学习画像
              </Button>
              <Button type="text" onClick={() => setOnboardingDismissed(true)}>
                稍后
              </Button>
            </Space>
          }
        >
          <Text type="secondary">
            补齐年级、学期和学习偏好后，助手制定计划时会更贴近真实情况。
          </Text>
          {onboardingOpen && (
            <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
              <Col xs={24} md={8}>
                <Text type="secondary">年级</Text>
                <Input
                  aria-label="年级"
                  value={onboardingForm.grade}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, grade: event.target.value }))}
                  placeholder="八年级"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">学期</Text>
                <Input
                  aria-label="学期"
                  value={onboardingForm.semester}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, semester: event.target.value }))}
                  placeholder="上册"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">学校</Text>
                <Input
                  aria-label="学校"
                  value={onboardingForm.school}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, school: event.target.value }))}
                  placeholder="可选"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">区县</Text>
                <Input
                  aria-label="区县"
                  value={onboardingForm.district}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, district: event.target.value }))}
                  placeholder="苏州工业园区"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">薄弱科目</Text>
                <Input
                  aria-label="薄弱科目"
                  value={onboardingForm.weakSubjects}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, weakSubjects: event.target.value }))}
                  placeholder="英语、数学"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">兴趣</Text>
                <Input
                  aria-label="兴趣"
                  value={onboardingForm.interests}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, interests: event.target.value }))}
                  placeholder="篮球、科普"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">偏好时段</Text>
                <Input
                  aria-label="偏好时段"
                  value={onboardingForm.preferredTime}
                  onChange={(event) => setOnboardingForm((form) => ({ ...form, preferredTime: event.target.value }))}
                  placeholder="下午"
                  style={{ marginTop: 6 }}
                />
              </Col>
              <Col xs={24} md={8}>
                <Text type="secondary">单次学习分钟数</Text>
                <InputNumber
                  aria-label="单次学习分钟数"
                  min={10}
                  max={90}
                  value={onboardingForm.sessionMinutes}
                  onChange={(value) => setOnboardingForm((form) => ({ ...form, sessionMinutes: Number(value ?? 25) }))}
                  style={{ width: '100%', marginTop: 6 }}
                />
              </Col>
              <Col span={24}>
                <Button type="primary" loading={savingOnboarding} onClick={() => void saveOnboarding()}>
                  保存画像
                </Button>
              </Col>
            </Row>
          )}
        </Card>
      )}

      {!snapshot ? (
        <Card>
          <Empty
            description={
              <span>
                学习档案尚未初始化。
                {role === 'parent'
                  ? '在对话页对助手说「帮我弟弟初始化学习档案，语文85数学90英语78体育80」即可'
                  : '请联系家长初始化'}
              </span>
            }
            style={{ padding: 40 }}
          />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {/* 雷达图 */}
          <Col xs={24} md={12}>
            <Card
              title={
                <>
                  <RadarChartOutlined /> 能力雷达
                </>
              }
              variant="borderless"
            >
              {radarHasData ? (
                <ResponsiveContainer width="100%" height={300}>
                  <RadarChart data={radarData}>
                    <PolarGrid stroke="var(--sb-color-border-warm)" />
                    <PolarAngleAxis
                      dataKey="subject"
                      tick={{ fill: 'var(--sb-color-text)', fontSize: 13 }}
                    />
                    <PolarRadiusAxis
                      domain={[0, 100]}
                      tick={{ fill: 'var(--sb-color-text-tertiary)', fontSize: 11 }}
                    />
                    <Radar
                      name="能力值"
                      dataKey="value"
                      stroke="var(--sb-color-primary)"
                      fill="var(--sb-color-primary)"
                      fillOpacity={0.12}
                    />
                  </RadarChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ padding: '40px 16px', textAlign: 'center' }}>
                  <RadarChartOutlined
                    style={{ fontSize: 36, color: 'var(--sb-color-text-placeholder)' }}
                  />
                  <div style={{ marginTop: 12 }}>
                    <Text type="secondary">数据不足</Text>
                  </div>
                  <div style={{ marginTop: 4, fontSize: 12, color: 'var(--sb-color-text-tertiary)' }}>
                    {role === 'parent'
                      ? '录入大考成绩后，能力雷达会显示真实水平'
                      : '等家长录入大考成绩后，这里会显示能力雷达'}
                  </div>
                </div>
              )}
            </Card>
          </Col>

          {/* 属性条 */}
          <Col xs={24} md={12}>
            <Card title="属性详情" variant="borderless">
              {ATTRIBUTE_SUBJECTS.map((s) => {
                const source = sources[s.key];
                const evidenced = Boolean(source);
                const value = snapshot?.[s.key];
                return (
                  <AttributeBar
                    key={s.key}
                    label={s.label}
                    value={evidenced ? value : undefined}
                    tip={s.tip}
                    source={source}
                    updatedAt={attrs?.created_at}
                  />
                );
              })}
              <div
                style={{
                  marginTop: 16,
                  paddingTop: 12,
                  borderTop: '1px solid var(--sb-color-bg-muted)',
                }}
              >
                <Text type="secondary">已掌握知识点</Text>
                {snapshot?.mastered_count === 0 || snapshot?.mastered_count == null ? (
                  <div style={{ marginTop: 4 }}>
                    <Text strong style={{ fontSize: 20, color: 'var(--sb-color-text-tertiary)' }}>
                      暂无
                    </Text>
                    <div
                      style={{ fontSize: 12, color: 'var(--sb-color-text-tertiary)', marginTop: 2 }}
                    >
                      还没有做过题或题目尚未判分，做题后这里会显示已掌握的知识点
                    </div>
                  </div>
                ) : (
                  <Text
                    strong
                    style={{ fontSize: 20, marginLeft: 8, color: 'var(--sb-color-success-strong)' }}
                  >
                    {snapshot.mastered_count} 个
                  </Text>
                )}
              </div>
            </Card>
          </Col>

          {/* 成长曲线 */}
          {(historyLoading || lineData.length > 1) && (
            <Col span={24}>
              <Card title="成长曲线" variant="borderless">
                {historyLoading ? (
                  <div style={{ padding: '32px 0', textAlign: 'center' }}>
                    <Spin />
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary">成长曲线加载中</Text>
                    </div>
                  </div>
                ) : lineData.some((d) => d.语文 !== null || d.数学 !== null || d.英语 !== null) ? (
                  <ResponsiveContainer width="100%" height={250}>
                    <LineChart data={lineData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--sb-color-border-warm)" />
                      <XAxis
                        dataKey="name"
                        tick={{ fill: 'var(--sb-color-text-soft)', fontSize: 12 }}
                      />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fill: 'var(--sb-color-text-soft)', fontSize: 11 }}
                      />
                      <ChartTooltip />
                      <Legend />
                      <Line type="monotone" dataKey="语文" stroke="var(--sb-color-primary)" />
                      <Line type="monotone" dataKey="数学" stroke="var(--sb-color-success-strong)" />
                      <Line type="monotone" dataKey="英语" stroke="var(--sb-color-orange-strong)" />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={{ padding: '24px 0', textAlign: 'center' }}>
                    <Text type="secondary">暂无有证据的能力变化</Text>
                    <div style={{ marginTop: 4, fontSize: 12, color: 'var(--sb-color-text-tertiary)' }}>
                      录入大考成绩或助教微调后，成长曲线会显示真实变化
                    </div>
                  </div>
                )}
              </Card>
            </Col>
          )}
        </Row>
      )}

      {/* 兴趣标签 */}
      <Card
        title={
          <>
            <HeartOutlined /> 兴趣标签
          </>
        }
        variant="borderless"
        style={{ marginTop: 16 }}
        extra={
          <Space size={8}>
            <Input.Search
              value={newInterest}
              onChange={(e) => setNewInterest(e.target.value)}
              enterButton={<Button icon={<PlusOutlined />}>{role === 'parent' ? '建议' : '添加'}</Button>}
              onSearch={handleAddInterest}
              placeholder={role === 'parent' ? '建议兴趣，如 天文' : '添加兴趣，如 篮球'}
              style={{ width: 240 }}
            />
          </Space>
        }
      >
        {interestsLoading ? (
          <Spin size="small" />
        ) : interests.length === 0 ? (
          <Text type="secondary">还没有登记兴趣</Text>
        ) : (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {interests.map((it) => (
              <Tag
                key={it.id}
                color={it.approved ? 'blue' : 'gold'}
                style={{ borderRadius: 12, padding: '2px 8px' }}
              >
                <Space size={6}>
                  <span>{it.tag}</span>
                  {!it.approved && <span>待学生确认</span>}
                  {role === 'student' && !it.approved && (
                    <>
                      <Button
                        size="small"
                        type="text"
                        icon={<CheckOutlined />}
                        loading={updatingInterestIds.has(it.id)}
                        onClick={() => void updateInterest(it.id, 'confirm')}
                      >
                        确认
                      </Button>
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<CloseOutlined />}
                        loading={updatingInterestIds.has(it.id)}
                        onClick={() => void updateInterest(it.id, 'remove')}
                      >
                        移除
                      </Button>
                    </>
                  )}
                </Space>
              </Tag>
            ))}
          </div>
        )}
      </Card>

      {role === 'parent' && boundaryLoading && (
        <Card title="推荐边界" variant="borderless" style={{ marginTop: 16 }}>
          <Spin size="small" />
        </Card>
      )}

      {role === 'parent' && !boundaryLoading && recommendationBoundary && (
        <Card title="推荐边界" variant="borderless" style={{ marginTop: 16 }}>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <Text type="secondary">允许平台</Text>
              <Select
                mode="tags"
                value={recommendationBoundary.allowed_platforms}
                onChange={(value) => updateBoundaryDraft({ allowed_platforms: value })}
                options={[{ value: 'bilibili', label: 'B 站' }]}
                tokenSeparators={[',', '，', ' ']}
                style={{ width: '100%', marginTop: 8 }}
              />
            </Col>
            <Col xs={24} md={8}>
              <Text type="secondary">屏蔽关键词</Text>
              <Select
                mode="tags"
                value={recommendationBoundary.blocked_keywords}
                onChange={(value) => updateBoundaryDraft({ blocked_keywords: value })}
                tokenSeparators={[',', '，', ' ']}
                placeholder="如 游戏直播、抽卡"
                style={{ width: '100%', marginTop: 8 }}
              />
            </Col>
            <Col xs={24} md={8}>
              <Text type="secondary">每日推荐上限</Text>
              <InputNumber
                min={0}
                max={20}
                value={recommendationBoundary.daily_limit}
                onChange={(value) => updateBoundaryDraft({ daily_limit: Number(value ?? 0) })}
                style={{ width: '100%', marginTop: 8 }}
              />
            </Col>
            <Col span={24}>
              <Checkbox
                checked={recommendationBoundary.allow_entertainment_interests}
                onChange={(event) =>
                  updateBoundaryDraft({ allow_entertainment_interests: event.target.checked })
                }
              >
                允许把娱乐兴趣用于学习资源推荐
              </Checkbox>
            </Col>
            <Col span={24}>
              <Button type="primary" loading={savingBoundary} onClick={() => void saveRecommendationBoundary()}>
                保存推荐边界
              </Button>
            </Col>
          </Row>
        </Card>
      )}
    </StudentPageShell>
  );
}

/** 属性条：有证据显示分数与来源；无证据显示「数据不足」，不展示假精确分。 */
function AttributeBar({
  label,
  value,
  tip,
  source,
  updatedAt,
}: {
  label: string;
  value?: number;
  tip?: string;
  source?: AttributeSubjectSource;
  updatedAt?: string;
}) {
  const evidenced = value !== undefined && value !== null;
  const pct = evidenced ? Math.min(100, value as number) : 0;
  const sourceLabel = source ? SOURCE_LABELS[source] : null;
  const labelText = (
    <>
      <Text style={{ color: 'var(--sb-color-text)' }}>{label}</Text>
      {tip && (
        <QuestionCircleOutlined
          style={{ fontSize: 12, color: 'var(--sb-color-text-placeholder)', marginLeft: 4 }}
        />
      )}
    </>
  );
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, alignItems: 'center' }}>
        {tip ? <Tooltip title={tip}>{labelText}</Tooltip> : labelText}
        {evidenced ? (
          <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 8 }}>
            {sourceLabel && (
              <Text
                style={{
                  fontSize: 11,
                  color: 'var(--sb-color-text-tertiary)',
                  background: 'var(--sb-color-bg-muted)',
                  border: '1px solid var(--sb-color-border-subtle)',
                  borderRadius: 8,
                  padding: '0 6px',
                }}
              >
                {sourceLabel}
              </Text>
            )}
            <Text
              strong
              style={{ color: (value as number) >= 80 ? 'var(--sb-color-success-strong)' : 'var(--sb-color-text)' }}
            >
              {value}
            </Text>
          </span>
        ) : (
          <Text style={{ fontSize: 12, color: 'var(--sb-color-text-tertiary)' }}>数据不足</Text>
        )}
      </div>
      <div
        style={{
          height: 8,
          background: 'var(--sb-color-track)',
          borderRadius: 4,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background:
              evidenced && (value as number) >= 80
                ? 'var(--sb-color-success-strong)'
                : 'var(--sb-color-attr-neutral)',
            borderRadius: 4,
            transition: 'width 0.6s ease',
          }}
        />
      </div>
      {evidenced && updatedAt && (
        <div style={{ fontSize: 11, color: 'var(--sb-color-text-tertiary)', marginTop: 2 }}>
          更新于 {updatedAt}
        </div>
      )}
    </div>
  );
}

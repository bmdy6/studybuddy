import { useEffect, useMemo, useState } from 'react';
import { Tree, Tag, Empty, Typography, Space, Card, App, theme, Button } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import type { TreeDataNode } from 'antd';
import {
  BookOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { errorBookApi } from '@/features/error_book/api';
import { learningFlowApi } from '@/features/learning/learningFlow';
import { SUBJECT_LABELS } from '@/shared/constants';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { getActiveStudentId, useAuthStore } from '@/features/auth/store';
import type { ErrorQuestionItem, ErrorSubjectGroup, ErrorTypeGroup } from '@/types';

const { Text, Title } = Typography;

/** 选中节点 key：`subject` 或 `subject|question_type` */
type SelectionKey = string;

export const buildErrorReviewNotePrompt = (question: ErrorQuestionItem) => {
  const tags = question.knowledge_tags?.length ? question.knowledge_tags.join('、') : '未标注';
  return [
    '请帮我把这道错题整理成一张复盘笔记。',
    '先根据下面的信息生成草稿，不要直接保存；等我确认或修改后，再调用 save_note 保存。',
    '请等待我确认、修改或拒绝；如果我拒绝或放弃整理，不要调用 save_note。',
    `保存时请使用 source=错题讲解，category=错题复盘，source_ref=[${question.error_id}]。`,
    `错题 ID：${question.error_id}`,
    `知识点：${tags}`,
    `题干：${question.stem}`,
    `我的错误答案：${question.student_answer || '未作答'}`,
    `正确答案：${question.correct_answer || '缺失，请先问我确认'}`,
    '请按“这题考什么 / 我为什么错 / 正确思路 / 下次提醒 / 相关知识点”整理，并体现我确认后的真实错因。',
  ].join('\n');
};

export default function ErrorBookPage() {
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const authState = useAuthStore();
  const studentId = getActiveStudentId(authState);
  const [groups, setGroups] = useState<ErrorSubjectGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedKey, setSelectedKey] = useState<SelectionKey | null>(null);
  const [visibleCount, setVisibleCount] = useState(10);
  const [reviewingErrorId, setReviewingErrorId] = useState<number | null>(null);
  // K2: 从知识路径/深链进入时按知识点过滤
  const [searchParams] = useSearchParams();
  const tagFilter = searchParams.get('knowledge_tag') ?? null;

  useEffect(() => {
    (async () => {
      try {
        const data = await errorBookApi.list(studentId ?? undefined);
        setGroups(data);
        // 默认选中第一个有错题的学科（数据驱动，无错题则不选中）
        const firstWithErrors = data.find((g) => g.total_count > 0);
        setSelectedKey(firstWithErrors?.subject ?? data[0]?.subject ?? null);
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '加载错题本失败';
        message.error(msg);
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message, studentId]);

  // 学科 → 错题组 映射，便于按 key 查找
  const groupMap = useMemo(() => {
    const m = new Map<string, ErrorSubjectGroup>();
    for (const g of groups) m.set(g.subject, g);
    return m;
  }, [groups]);

  // 构建左侧树：数据驱动——按后端返回的实际学科(如「英语」)建文件夹，
  // 每个学科下挂题型子节点。SUBJECT_LABELS 命中转标签，否则原样展示。
  const treeData: TreeDataNode[] = useMemo(() => {
    return groups.map((group) => {
      const subject = group.subject;
      const total = group.total_count;
      const children: TreeDataNode[] = group.type_groups.map((tg) => ({
        key: `${subject}|${tg.question_type}`,
        title: (
          <Space size={6}>
            <FileTextOutlined style={{ color: token.colorTextSecondary }} />
            <Text>{tg.type_label}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {tg.error_count}
            </Text>
          </Space>
        ),
        icon: <FileTextOutlined />,
      }));
      return {
        key: subject,
        title: (
          <Space size={6}>
            <Text strong>{SUBJECT_LABELS[subject] ?? subject}</Text>
            {total > 0 && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {total}
              </Text>
            )}
          </Space>
        ),
        icon: total > 0 ? <FolderOpenOutlined /> : <FolderOutlined />,
        children,
      };
    });
  }, [groups, token.colorTextSecondary]);

  // 默认展开全部有子节点的学科
  const expandedKeys = useMemo(
    () => groups.filter((g) => g.type_groups.length > 0).map((g) => g.subject),
    [groups],
  );

  // 选中节点 → 右侧要展示的错题列表 + 标题（K2: 支持 knowledge_tag 过滤）
  const { viewTitle, viewQuestions } = useMemo(() => {
    if (!selectedKey) return { viewTitle: '', viewQuestions: [] as ErrorQuestionItem[] };
    const group = groupMap.get(selectedKey);
    let questions: ErrorQuestionItem[] = [];
    let title = '';
    if (group) {
      // 选中学科根节点：该学科全部错题
      const all: ErrorQuestionItem[] = [];
      for (const tg of group.type_groups) all.push(...tg.questions);
      title = SUBJECT_LABELS[selectedKey] ?? selectedKey;
      questions = all;
    } else {
      // 选中题型节点：subject|question_type
      const [subject, qtype] = selectedKey.split('|');
      const g = groupMap.get(subject);
      const tg: ErrorTypeGroup | undefined = g?.type_groups.find((t) => t.question_type === qtype);
      title = `${SUBJECT_LABELS[subject] ?? subject} · ${tg?.type_label ?? qtype}`;
      questions = tg?.questions ?? [];
    }
    if (tagFilter) {
      const hit = (q: ErrorQuestionItem) => (q.knowledge_tags ?? []).includes(tagFilter);
      const filtered = questions.filter(hit);
      return { viewTitle: `${title} · ${tagFilter}`, viewQuestions: filtered };
    }
    return { viewTitle: title, viewQuestions: questions };
  }, [selectedKey, groupMap, tagFilter]);

  if (loading) {
    return (
      <PageSpinner padding={120} />
    );
  }

  const totalErrors = groups.reduce((s, g) => s + g.total_count, 0);
  const openPracticeChat = async (question: ErrorQuestionItem) => {
    if (!studentId) return;
    setReviewingErrorId(question.error_id);
    try {
      const entry = await learningFlowApi.getReviewEntry({ studentId, errorId: question.error_id });
      const params = new URLSearchParams({ student_id: String(studentId), prompt: entry.prompt });
      navigate(`/chat?${params.toString()}`);
    } catch {
      message.error('暂时无法开始复习，请稍后重试');
    } finally {
      setReviewingErrorId(null);
    }
  };
  const openReviewNoteChat = (question: ErrorQuestionItem) => {
    const params = new URLSearchParams({
      ...(studentId ? { student_id: String(studentId) } : {}),
      prompt: buildErrorReviewNotePrompt(question),
    });
    navigate(`/chat?${params.toString()}`);
  };
  // 保留整理复盘笔记入口：从"开始复习"进入对话后，Agent 可引导整理
  void openReviewNoteChat;

  if (groups.length === 0) {
    return (
      <StudentPageShell
        title="错题本"
        subtitle="现在还没有错题，继续保持。"
        icon={<BookOutlined />}
        maxWidth={1000}
      >
        <Card style={{ borderRadius: 12 }}>
          <Empty description="还没有错题，继续保持！" style={{ padding: '44px 0' }}>
            <Button
              type="primary"
              onClick={() =>
                navigate(
                  `/chat?prompt=${encodeURIComponent('我要拍题批改今天的作业')}${
                    studentId ? `&student_id=${studentId}` : ''
                  }`,
                )
              }
            >
              去拍题批改
            </Button>
          </Empty>
        </Card>
      </StudentPageShell>
    );
  }

  return (
    <StudentPageShell
      title="错题本"
      subtitle="把做错的题集中起来复盘，再让助手生成同类练习。"
      icon={<BookOutlined />}
      metrics={[
        { label: '学科', value: `${groups.length} 个` },
        { label: '错题', value: `${totalErrors} 道`, tone: totalErrors ? 'warning' : 'success' },
      ]}
      maxWidth={1000}
    >
      {/* 手机端筛选 chips（Stitch screen 10） */}
      <div className="sb-error-chips" role="tablist" aria-label="学科筛选">
        {groups.map((group) => (
          <button
            type="button"
            key={group.subject}
            className={`sb-error-chip${selectedKey === group.subject ? ' is-active' : ''}`}
            onClick={() => {
              setSelectedKey(group.subject);
              setVisibleCount(10);
            }}
            role="tab"
            aria-selected={selectedKey === group.subject}
          >
            {SUBJECT_LABELS[group.subject] ?? group.subject}
            {group.total_count > 0 && <span className="sb-error-chip-count">{group.total_count}</span>}
          </button>
        ))}
      </div>

      <div className="sb-learning-grid">
        {/* 左侧学科树（桌面端） */}
        <Card
          className="sb-error-tree-card"
          style={{ width: 240, flexShrink: 0, borderRadius: 12, position: 'sticky', top: 88 }}
          styles={{ body: { padding: 12 } }}
        >
          <Tree
            treeData={treeData}
            showIcon
            blockNode
            defaultExpandedKeys={expandedKeys}
            selectedKeys={selectedKey ? [selectedKey] : []}
            onSelect={(keys) => {
              if (keys.length > 0) setSelectedKey(keys[0] as string);
            }}
            style={{ background: 'transparent' }}
          />
        </Card>

        {/* 右侧错题列表 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="sb-error-list-head">
            <Title level={4} style={{ marginBottom: 0 }}>
              {viewTitle}
            </Title>
            {viewQuestions.length > 0 && <Text type="secondary">{viewQuestions.length} 题</Text>}
          </div>

          {viewQuestions.length === 0 ? (
            <Empty description="该分类暂无错题，继续保持" style={{ marginTop: 80 }} />
          ) : (
            <>
              <div className="sb-error-list">
                {viewQuestions.slice(0, visibleCount).map((q, idx) => (
                  <div className="sb-error-item" key={q.question_id}>
                    <div className="sb-error-item-main">
                      <Text className="sb-error-item-stem">
                        <span className="sb-error-item-num">{idx + 1}</span>
                        {q.stem}
                      </Text>
                      <div className="sb-error-item-tags">
                        <Tag className="sb-error-item-subject">
                          {SUBJECT_LABELS[selectedKey?.split('|')[0] ?? ''] ?? selectedKey ?? ''}
                        </Tag>
                        {q.knowledge_tags?.slice(0, 3).map((t) => (
                          <Tag key={t}>{t}</Tag>
                        ))}
                        <Text className="sb-error-item-count">错 {q.error_count} 次</Text>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="sb-error-item-review"
                      onClick={() => void openPracticeChat(q)}
                      disabled={reviewingErrorId === q.error_id}
                      aria-label={`开始复习 ${q.stem.slice(0, 20)}`}
                    >
                      开始复习
                    </button>
                  </div>
                ))}
              </div>
              {viewQuestions.length > visibleCount && (
                <div className="sb-error-show-more">
                  <button
                    type="button"
                    onClick={() => setVisibleCount((c) => c + 10)}
                  >
                    显示更多（还有 {viewQuestions.length - visibleCount} 题）
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </StudentPageShell>
  );
}

import { useEffect, useMemo, useState } from 'react';
import dayjs from 'dayjs';
import { useNavigate } from 'react-router-dom';
import { Card, Row, Col, Tag, Button, Empty, Skeleton, Typography, Space, App } from 'antd';
import {
  FileTextOutlined,
  ArrowRightOutlined,
  ReloadOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { examApi } from '@/features/exams/exam';
import { useAuth } from '@/features/auth/useAuth';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { SUBJECT_LABELS } from '@/shared/constants';
import type { ExamListItem } from '@/types';

const { Title, Text } = Typography;

// 学生完成状态 -> 卡片标签。None（未做）显示"可练习"。
const completionMeta: Record<string, { label: string; className: string }> = {
  in_progress: { label: '进行中', className: 'sb-status-chip sb-status-chip--reviewing' },
  submitted: { label: '批改中', className: 'sb-status-chip sb-status-chip--warning' },
  graded: { label: '已完成', className: 'sb-status-chip sb-status-chip--confirmed' },
};

function ExamSkeletonCard() {
  return (
    <Card style={{ borderRadius: 12, height: '100%' }}>
      <Skeleton active paragraph={{ rows: 3 }} />
    </Card>
  );
}

export default function ExamListPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { displayName } = useAuth();
  const [exams, setExams] = useState<ExamListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [subjectFilter, setSubjectFilter] = useState<string>('all');

  const loadExams = async () => {
    setLoading(true);
    try {
      const data = await examApi.list();
      setExams(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载试卷列表失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openExam = (examId: number) => {
    navigate(`/exams/${examId}/take`);
  };

  const viewResult = (examId: number, recordId: number) => {
    navigate(`/exams/${examId}/result`, { state: { examRecordId: recordId } });
  };

  const formatSubject = (subject: string) => SUBJECT_LABELS[subject] ?? subject;
  const totalQuestions = exams.reduce((sum, exam) => sum + exam.question_count, 0);
  const completedCount = exams.filter((e) => e.latest_record_status === 'graded').length;

  // 科目筛选胶囊：全部 + 实际出现的科目
  const subjectOptions = useMemo(() => {
    const set = new Set(exams.map((e) => e.subject).filter(Boolean));
    return ['all', ...Array.from(set)];
  }, [exams]);

  const filteredExams = useMemo(() => {
    if (subjectFilter === 'all') return exams;
    return exams.filter((e) => e.subject === subjectFilter);
  }, [exams, subjectFilter]);

  return (
    <StudentPageShell
      title={displayName ? `${displayName}，欢迎回来` : '我的试卷'}
      subtitle="选择一份试卷开始练习；做完后会自动进入结果页和错题复盘。"
      icon={<FileTextOutlined />}
      actions={
        <Button type="default" icon={<ReloadOutlined />} onClick={loadExams} loading={loading}>
          刷新
        </Button>
      }
      metrics={[
        { label: '可练习试卷', value: exams.length },
        { label: '已完成', value: completedCount },
        { label: '总题量', value: `${totalQuestions} 题` },
      ]}
      maxWidth={1100}
    >
      {/* 科目筛选：一排小胶囊，手机上好点 */}
      {!loading && exams.length > 0 && (
        <Space size={[8, 8]} wrap style={{ marginBottom: 16 }}>
          {subjectOptions.map((s) => (
            <Tag.CheckableTag
              key={s}
              checked={subjectFilter === s}
              onChange={() => setSubjectFilter(s)}
            >
              {s === 'all' ? '全部' : formatSubject(s)}
            </Tag.CheckableTag>
          ))}
        </Space>
      )}

      {loading ? (
        <Row gutter={[20, 20]}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Col key={i} xs={24} sm={12} lg={8}>
              <ExamSkeletonCard />
            </Col>
          ))}
        </Row>
      ) : filteredExams.length === 0 ? (
        <Card style={{ borderRadius: 12 }}>
          <Empty
            description={
              exams.length === 0 ? '现在还没有可练习的试卷' : '该科目下没有试卷'
            }
          >
            {exams.length === 0 && (
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={loadExams}
                loading={loading}
              >
                重新加载
              </Button>
            )}
          </Empty>
        </Card>
      ) : (
        <Row gutter={[20, 20]}>
          {filteredExams.map((exam) => {
            const comp = exam.latest_record_status;
            const meta = comp ? completionMeta[comp] : null;
            const isSubmitted = comp === 'submitted' && Boolean(exam.latest_record_id);
            const isGraded = comp === 'graded' && Boolean(exam.latest_record_id);
            const canViewResult = (isSubmitted || isGraded) && exam.latest_record_id;
            const openCard = () => {
              if (canViewResult) {
                viewResult(exam.id, exam.latest_record_id!);
                return;
              }
              openExam(exam.id);
            };
            const actionText = isGraded
              ? '再练一次'
              : isSubmitted
                ? '查看批改'
                : comp === 'in_progress'
                  ? '继续'
                  : '开始';
            return (
              <Col key={exam.id} xs={24} sm={12} lg={8}>
                <Card
                  className="app-card-hover"
                  style={{
                    height: '100%',
                    borderRadius: 12,
                    cursor: 'pointer',
                    position: 'relative',
                  }}
                  onClick={openCard}
                >
                  {exam.has_new && <span className="new-badge" />}

                  <Space direction="vertical" size={12} style={{ width: '100%', minHeight: 140 }}>
                    <div>
                      <Tag className={meta ? meta.className : 'sb-status-chip sb-status-chip--confirmed'} style={{ marginBottom: 8 }}>
                        {meta ? meta.label : '可练习'}
                      </Tag>
                    </div>
                    <Title
                      level={5}
                      style={{ marginBottom: 0, lineHeight: 1.4 }}
                      ellipsis={{ rows: 2 }}
                    >
                      {exam.title}
                    </Title>
                    <Text type="secondary" style={{ fontSize: 14 }}>
                      {formatSubject(exam.subject)}
                    </Text>
                    {(exam.assignment_note || exam.assignment_due_at) && (
                      <Space
                        direction="vertical"
                        size={4}
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          background: 'var(--sb-color-fill-soft, #f5f7fa)',
                          borderRadius: 8,
                        }}
                      >
                        {exam.assignment_note && (
                          <Text style={{ fontSize: 13 }}>{exam.assignment_note}</Text>
                        )}
                        {exam.assignment_due_at && (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            截止 {dayjs(exam.assignment_due_at).format('MM-DD HH:mm')}
                          </Text>
                        )}
                      </Space>
                    )}

                    <div
                      data-testid={`exam-card-footer-${exam.id}`}
                      style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '10px 12px',
                        marginTop: 'auto',
                        paddingTop: 12,
                        borderTop: '1px solid var(--sb-color-border-subtle)',
                      }}
                    >
                      <Space size={12} style={{ flex: '0 0 auto', whiteSpace: 'nowrap' }}>
                        <Space size={4}>
                          <FileTextOutlined style={{ color: 'var(--sb-color-text-secondary)' }} />
                          <Text
                            data-testid={`exam-question-count-${exam.id}`}
                            type="secondary"
                            style={{ fontSize: 13, whiteSpace: 'nowrap' }}
                          >
                            {exam.question_count} 题
                          </Text>
                        </Space>
                        <Text
                          data-testid={`exam-total-score-${exam.id}`}
                          type="secondary"
                          style={{ fontSize: 13, whiteSpace: 'nowrap' }}
                        >
                          {exam.total_score} 分
                        </Text>
                      </Space>
                      <Space
                        size={4}
                        style={{ flex: '0 0 auto', marginLeft: 'auto', whiteSpace: 'nowrap' }}
                      >
                        {isGraded && (
                          <Button
                            size="small"
                            icon={<EyeOutlined />}
                            onClick={(e) => {
                              e.stopPropagation();
                              viewResult(exam.id, exam.latest_record_id!);
                            }}
                          >
                            看错题
                          </Button>
                        )}
                        <Button
                          type="link"
                          size="small"
                          style={{ padding: 0 }}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (isSubmitted) {
                              viewResult(exam.id, exam.latest_record_id!);
                              return;
                            }
                            openExam(exam.id);
                          }}
                        >
                          {actionText} <ArrowRightOutlined />
                        </Button>
                      </Space>
                    </div>
                  </Space>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}
    </StudentPageShell>
  );
}

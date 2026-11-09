import { useEffect, useState } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import {
  Result,
  Button,
  Card,
  Typography,
  Space,
  Tag,
  Statistic,
  Row,
  Col,
  Alert,
  App,
} from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import { answerApi } from '@/features/exams/answer';
import { examApi } from '@/features/exams/exam';
import { p2Api } from '@/features/p2/api';
import { ROLES } from '@/shared/constants';
import { usePolling } from '@/features/exams/hooks/usePolling';
import { getActiveStudentId, useAuthStore } from '@/features/auth/store';
import type { ExamDetail, ExamRecordAnswerResult, ExamRecordResult } from '@/types';

const { Text } = Typography;
const WRONG_REASON_OPTIONS = [
  '粗心',
  '概念不清',
  '审题错误',
  '公式/规则不熟',
  '不会做',
  '时间不够',
];

interface ResultState {
  examRecordId?: number;
  objectiveScore?: number;
  pendingManualCount?: number;
}

export default function ExamResultPage() {
  const { examId } = useParams<{ examId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const state = (location.state as ResultState | null) ?? {};
  const query = new URLSearchParams(location.search);
  const queryRecordId = Number(query.get('exam_record_id'));
  const queryPlanItemId = Number(query.get('plan_item_id'));
  const examRecordId = state.examRecordId ?? (Number.isInteger(queryRecordId) && queryRecordId > 0 ? queryRecordId : undefined);
  const planItemId = Number.isInteger(queryPlanItemId) && queryPlanItemId > 0 ? queryPlanItemId : undefined;
  const authState = useAuthStore();
  const studentId = getActiveStudentId(authState);
  const canSubmitReason = authState.role === ROLES.STUDENT && studentId !== null;

  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [recordResult, setRecordResult] = useState<ExamRecordResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [reasonSavingId, setReasonSavingId] = useState<number | null>(null);
  const [savedReasons, setSavedReasons] = useState<Record<number, string>>({});

  const { isGrading, pendingCount } = usePolling({
    examRecordId: examRecordId ?? null,
    intervalMs: 5000,
    enabled: (state.pendingManualCount ?? 0) > 0,
  });

  useEffect(() => {
    if (!examId) return;
    (async () => {
      try {
        const detail = await examApi.detail(Number(examId));
        setExam(detail);
      } catch {
        message.error('加载试卷信息失败');
      } finally {
        setLoading(false);
      }
    })();
  }, [examId, message]);

  useEffect(() => {
    const recordId = examRecordId;
    if (!recordId) return;
    (async () => {
      try {
        const result = await answerApi.result(recordId);
        setRecordResult(result);
      } catch {
        message.warning('暂时没有加载到本次作答明细');
      }
    })();
  }, [message, examRecordId]);

  if (loading) {
    return (
      <PageSpinner padding={120} />
    );
  }

  const hasPending = (state.pendingManualCount ?? 0) > 0;
  const wrongAnswers = recordResult?.answers.filter((answer) => answer.is_correct === false) ?? [];

  const formatAnswer = (value: string | null) => {
    if (!value) return '未填写';
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.join('、');
      if (typeof parsed === 'string') return parsed;
    } catch {
      // 普通文本答案不需要 JSON 解析。
    }
    return value;
  };

  const buildReasonContent = (
    answer: ExamRecordAnswerResult,
    reason: string,
    questionIndex: number,
  ) => {
    const tags = answer.knowledge_tags.length > 0 ? answer.knowledge_tags.join('、') : '未标注';
    return [
      `错题原因：第 ${questionIndex} 题「${answer.question_stem.slice(0, 80)}」`,
      `错因：${reason}`,
      `我的答案：${formatAnswer(answer.student_answer)}`,
      `正确答案：${formatAnswer(answer.correct_answer)}`,
      `知识点：${tags}`,
    ].join('；');
  };

  const submitWrongReason = async (
    answer: ExamRecordAnswerResult,
    reason: string,
    questionIndex: number,
  ) => {
    if (!studentId) {
      message.warning('只有学生账号可以记录错因');
      return;
    }
    setReasonSavingId(answer.answer_id);
    try {
      await p2Api.submitFeedback(
        studentId,
        'difficulty',
        buildReasonContent(answer, reason, questionIndex),
        answer.answer_id,
      );
      setSavedReasons((prev) => ({ ...prev, [answer.answer_id]: reason }));
      message.success('已记录错因');
    } catch {
      message.error('错因记录失败，请稍后再试');
    } finally {
      setReasonSavingId(null);
    }
  };

  return (
    <div className="exam-result-page fade-in">
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/exams')}
        style={{ marginBottom: 16 }}
      >
        返回试卷列表
      </Button>

      {hasPending && (
        <Alert
          type={isGrading ? 'info' : 'success'}
          showIcon
          icon={isGrading ? <ClockCircleOutlined /> : <CheckCircleOutlined />}
          message={
            isGrading
              ? `教师正在批改主观题，还有 ${pendingCount} 题待批改…`
              : '所有题目已批改完成！'
          }
          description={isGrading ? '页面会自动刷新，请稍候' : '可以查看最终成绩了'}
          style={{ marginBottom: 24, borderRadius: 12 }}
          action={
            isGrading ? (
              <Button type="text" icon={<ReloadOutlined />} loading>
                刷新中
              </Button>
            ) : undefined
          }
        />
      )}

      <Card className="exam-result-hero-card" style={{ borderRadius: 12, textAlign: 'center' }}>
        <Result
          icon={
            <CheckCircleOutlined
              style={{
                color:
                  hasPending && isGrading ? 'var(--sb-color-warning)' : 'var(--sb-color-success)',
              }}
            />
          }
          title={hasPending && isGrading ? '答题已提交，等待批改' : '交卷成功！'}
          subTitle={exam?.title ?? '试卷'}
          extra={
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Row gutter={{ xs: 16, sm: 48 }} justify="center">
                <Col xs={24} sm={8}>
                  <Statistic
                    title="客观题得分"
                    value={state.objectiveScore ?? 0}
                    suffix="分"
                    valueStyle={{ color: 'var(--sb-color-primary)' }}
                  />
                </Col>
                <Col xs={24} sm={8}>
                  <Statistic
                    title="满分"
                    value={exam?.questions.reduce((s, q) => s + q.score, 0) ?? 0}
                    suffix="分"
                  />
                </Col>
                <Col xs={24} sm={8}>
                  <Statistic title="待批改" value={isGrading ? pendingCount : 0} suffix="题" />
                </Col>
              </Row>

              <Space wrap>
                {planItemId && examRecordId ? (
                  <Button
                    type="primary"
                    onClick={() =>
                      navigate(
                        `/chat?continue_task_item=${planItemId}&practice_exam_record=${examRecordId}`,
                      )
                    }
                  >
                    返回学习任务复盘
                  </Button>
                ) : null}
                <Button type={planItemId ? 'default' : 'primary'} onClick={() => navigate('/exams')}>
                  返回试卷列表
                </Button>
                <Button onClick={() => navigate('/diagnosis')}>查看学情诊断</Button>
              </Space>
            </Space>
          }
        />
      </Card>

      {wrongAnswers.length > 0 && (
        <Card
          title="错因记录"
          style={{ borderRadius: 12, marginTop: 20 }}
          styles={{ body: { padding: 24 } }}
        >
          {!canSubmitReason && (
            <Alert
              type="info"
              showIcon
              message="错因需要学生自己确认"
              style={{ marginBottom: 16, borderRadius: 10 }}
            />
          )}
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {wrongAnswers.map((answer) => {
              const questionIndex =
                (recordResult?.answers.findIndex((item) => item.answer_id === answer.answer_id) ??
                  0) + 1;
              const savedReason = savedReasons[answer.answer_id];
              return (
                <div
                  key={answer.answer_id}
                  style={{
                    paddingBottom: 16,
                    borderBottom: '1px solid var(--sb-color-border-subtle)',
                  }}
                >
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Space wrap>
                      <Tag color="red">第 {questionIndex} 题</Tag>
                      {answer.knowledge_tags.map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </Space>
                    <Text>{answer.question_stem}</Text>
                    <Text type="secondary">
                      我的答案：{formatAnswer(answer.student_answer)}；正确答案：
                      {formatAnswer(answer.correct_answer)}
                    </Text>
                    <Space wrap>
                      {WRONG_REASON_OPTIONS.map((reason) => (
                        <Button
                          key={reason}
                          size="small"
                          type={savedReason === reason ? 'primary' : 'default'}
                          loading={reasonSavingId === answer.answer_id && savedReason !== reason}
                          disabled={!canSubmitReason || Boolean(savedReason)}
                          onClick={() => submitWrongReason(answer, reason, questionIndex)}
                        >
                          {savedReason === reason ? `已记录：${reason}` : reason}
                        </Button>
                      ))}
                    </Space>
                  </Space>
                </div>
              );
            })}
          </Space>
        </Card>
      )}

      {exam && (
        <Card
          title="试卷概览"
          style={{ borderRadius: 12, marginTop: 20 }}
          styles={{ body: { padding: 24 } }}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {exam.questions.map((q, i) => (
              <div key={q.id} className="exam-overview-row">
                <Space>
                  <Tag>第 {i + 1} 题</Tag>
                  <Text type="secondary" ellipsis className="exam-overview-stem">
                    {q.stem.slice(0, 60)}
                    {q.stem.length > 60 ? '…' : ''}
                  </Text>
                </Space>
                <Text type="secondary">{q.score} 分</Text>
              </div>
            ))}
          </Space>
        </Card>
      )}
    </div>
  );
}

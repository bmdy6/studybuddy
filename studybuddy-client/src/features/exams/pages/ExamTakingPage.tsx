import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { Card, Button, Result, Typography, Space, Tag, App, Drawer, Modal } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  ClockCircleOutlined,
  LeftOutlined,
  CheckCircleOutlined,
  StarOutlined,
  StarFilled,
} from '@ant-design/icons';
import { examApi } from '@/features/exams/exam';
import { answerApi } from '@/features/exams/answer';
import { useExamStore } from '@/features/exams/store';
import QuestionCard from '@/shared/components/QuestionCard';
import type { ExamDetail, StartExamResponse, QuestionType } from '@/types';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Text } = Typography;

/** 单选题选完后自动跳下一题的延迟（ms），防误触、给用户看清选中态 */
const AUTO_ADVANCE_DELAY = 400;
/** 答题页内容最大宽度：手机端满宽，桌面端用受控阅读宽度（D1：不再固定 480 窄条） */
const CONTENT_MAX_WIDTH = READING_COLUMN_MAX;

const typeLabel: Record<string, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  transform: '转换题',
  translation: '翻译题',
  essay: '简答题',
  math_answer: '解答题',
};

export default function ExamTakingPage() {
  const { examId } = useParams<{ examId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const planItemIdRaw = new URLSearchParams(location.search).get('plan_item_id');
  const planItemId = planItemIdRaw && Number.isInteger(Number(planItemIdRaw)) ? Number(planItemIdRaw) : undefined;
  const { message } = App.useApp();
  const examStore = useExamStore();

  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [examRecord, setExamRecord] = useState<StartExamResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [elapsed, setElapsed] = useState(0); // 秒
  const [cardOpen, setCardOpen] = useState(false); // 答题卡抽屉
  const [confirmOpen, setConfirmOpen] = useState(false); // 交卷确认弹窗
  const loadingExamIdRef = useRef<number | null>(null);
  const autoAdvanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelAutoAdvance = useCallback(() => {
    if (!autoAdvanceTimer.current) return;
    clearTimeout(autoAdvanceTimer.current);
    autoAdvanceTimer.current = null;
  }, []);

  // 加载试卷详情 + 开启考试记录
  useEffect(() => {
    if (!examId) return;
    const id = Number(examId);
    if (loadingExamIdRef.current === id) return;
    let active = true;
    loadingExamIdRef.current = id;
    cancelAutoAdvance();
    setCurrentIdx(0);
    setCardOpen(false);
    setElapsed(0);
    setExam(null);
    setExamRecord(null);

    (async () => {
      setLoading(true);
      try {
        const detail = await examApi.detail(id);
        if (!active) return;

        let record: StartExamResponse;
        let startedAt: number | null = null;
        if (examStore.activeRecord && examStore.activeRecord.exam_id === id) {
          record = {
            exam_record_id: examStore.activeRecord.exam_record_id,
            exam_id: id,
            status: 'in_progress',
          };
          startedAt = examStore.activeRecord.started_at;
        } else {
          record = await examApi.start(id);
          if (!active) return;
          examStore.setActiveRecord({
            exam_id: id,
            exam_record_id: record.exam_record_id,
            started_at: Date.now(),
          });
        }

        if (!active) return;
        setExam(detail);
        setExamRecord(record);
        if (startedAt !== null) {
          setElapsed(Math.floor((Date.now() - startedAt) / 1000));
        }
      } catch (err: unknown) {
        if (!active) return;
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '加载试卷失败';
        message.error(msg);
      } finally {
        if (active) {
          setLoading(false);
          loadingExamIdRef.current = null;
        }
      }
    })();

    return () => {
      active = false;
      cancelAutoAdvance();
      if (loadingExamIdRef.current === id) loadingExamIdRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examId, cancelAutoAdvance]);

  // 计时器
  useEffect(() => {
    const timer = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // 卸载时清理自动跳题定时器
  useEffect(() => cancelAutoAdvance, [cancelAutoAdvance]);

  const getAnswer = useCallback(
    (qId: number): string => {
      if (!examRecord) return '';
      return examStore.getDraft(examRecord.exam_record_id, qId) ?? '';
    },
    [examRecord, examStore],
  );

  const setAnswer = useCallback(
    (qId: number, answer: string) => {
      if (!examRecord) return;
      examStore.setDraft(examRecord.exam_record_id, qId, answer);
    },
    [examRecord, examStore],
  );

  // 用 forceUpdate 触发重渲染（zustand 非响应式 getDraft）
  const [, setTick] = useState(0);
  const forceUpdate = () => setTick((t) => t + 1);

  const questionCount = exam?.questions.length ?? 0;

  const handleAnswerChange = (qId: number, qType: QuestionType, isLast: boolean) => {
    return (answer: string) => {
      // 去重：值未变不重复触发（Radio onChange + 外层 mousedown 可能各触发一次）
      if (getAnswer(qId) === answer) return;
      setAnswer(qId, answer);
      forceUpdate();
      cancelAutoAdvance();

      // 单选选完自动跳下一题；末题不跳（变交卷）
      if (qType === 'single_choice' && !isLast) {
        const sourceIndex = currentIdx;
        autoAdvanceTimer.current = setTimeout(() => {
          autoAdvanceTimer.current = null;
          setCurrentIdx((index) =>
            index === sourceIndex ? Math.min(index + 1, questionCount - 1) : index,
          );
        }, AUTO_ADVANCE_DELAY);
      }
    };
  };

  const selectQuestion = (index: number) => {
    cancelAutoAdvance();
    setCurrentIdx(Math.max(0, Math.min(index, questionCount - 1)));
  };

  const goPrev = () => {
    cancelAutoAdvance();
    setCurrentIdx((index) => Math.max(0, index - 1));
  };

  const goNext = () => {
    cancelAutoAdvance();
    setCurrentIdx((index) => Math.min(questionCount - 1, index + 1));
  };

  const openAnswerCard = () => {
    cancelAutoAdvance();
    setCardOpen(true);
  };

  const leaveExam = () => {
    cancelAutoAdvance();
    navigate('/exams');
  };

  const toggleMarkCurrent = () => {
    cancelAutoAdvance();
    if (!examRecord || !exam) return;
    examStore.toggleMark(examRecord.exam_record_id, exam.questions[currentIdx].id);
    forceUpdate();
  };

  const isMarked = (qId: number) =>
    examRecord ? examStore.isMarked(examRecord.exam_record_id, qId) : false;

  const answeredCount = exam
    ? exam.questions.filter((q) => getAnswer(q.id).trim().length > 0).length
    : 0;

  const handleSubmit = () => {
    if (!exam || !examRecord) return;
    cancelAutoAdvance();
    setConfirmOpen(true);
  };

  const doSubmit = async () => {
    if (!exam || !examRecord) return;
    setSubmitting(true);
    try {
      const submitResult = await answerApi.submit(exam.id, {
        exam_record_id: examRecord.exam_record_id,
        answers: exam.questions.map((q) => ({
          question_id: q.id,
          student_answer: getAnswer(q.id),
        })),
      });
      examStore.clearDraft(examRecord.exam_record_id);
      examStore.setActiveRecord(null);
      setConfirmOpen(false);
      message.success('交卷成功！');
      navigate(
        `/exams/${exam.id}/result?exam_record_id=${examRecord.exam_record_id}${planItemId ? `&plan_item_id=${planItemId}` : ''}`,
        {
          state: {
            examRecordId: examRecord.exam_record_id,
            objectiveScore: submitResult.objective_score,
            pendingManualCount: submitResult.pending_manual_count,
          },
        },
      );
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '交卷失败，请重试';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <PageSpinner padding={120} />
    );
  }

  if (!exam || !examRecord) {
    return (
      <Result
        status="error"
        title="试卷加载失败"
        extra={<Button onClick={() => navigate('/exams')}>返回列表</Button>}
      />
    );
  }

  const questions = exam.questions;
  if (questions.length === 0) {
    return (
      <Result
        status="info"
        title="试卷暂无题目"
        extra={<Button onClick={leaveExam}>返回列表</Button>}
      />
    );
  }

  const currentQ = questions[currentIdx];
  const total = questions.length;
  const isLast = currentIdx === total - 1;
  const currentMarked = isMarked(currentQ.id);

  return (
    <div
      data-testid="exam-taking-page"
      style={{
        minHeight: '100dvh',
        maxWidth: `min(100%, ${CONTENT_MAX_WIDTH}px)`,
        margin: '0 auto',
        background: 'var(--sb-color-bg)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* 顶部状态栏 */}
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          background: 'var(--sb-color-white)',
          borderBottom: '1px solid var(--sb-color-border-secondary)',
          padding: '10px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        <Space size={6}>
          <Button type="text" icon={<LeftOutlined />} aria-label="退出" onClick={leaveExam} />
          <Tag color="blue" style={{ margin: 0 }}>
            {typeLabel[currentQ.type] ?? currentQ.type}
          </Tag>
          <Button
            type="text"
            size="small"
            aria-label="标记本题"
            icon={
              currentMarked ? (
                <StarFilled style={{ color: 'var(--sb-color-warning)' }} />
              ) : (
                <StarOutlined />
              )
            }
            onClick={toggleMarkCurrent}
          />
        </Space>
        <Space size={10}>
          <Space size={4}>
            <ClockCircleOutlined style={{ color: 'var(--sb-color-warning)', fontSize: 14 }} />
            <Text style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 500 }}>
              {formatTime(elapsed)}
            </Text>
          </Space>
          <Button
            type="primary"
            danger
            size="small"
            icon={<CheckCircleOutlined />}
            loading={submitting}
            onClick={handleSubmit}
          >
            交卷
          </Button>
        </Space>
      </div>

      {/* 题目区 */}
      <div data-testid="exam-question-section" style={{ padding: 16, flex: 1 }}>
        <Card style={{ borderRadius: 12 }} styles={{ body: { padding: '8px 16px' } }}>
          <QuestionCard
            question={currentQ}
            index={currentIdx}
            value={getAnswer(currentQ.id)}
            onChange={handleAnswerChange(currentQ.id, currentQ.type, isLast)}
          />
        </Card>
        <Text
          type="secondary"
          style={{ display: 'block', textAlign: 'center', fontSize: 12, marginTop: 8 }}
        >
          第 {currentIdx + 1} / {total} 题
        </Text>
      </div>

      {/* 底部翻页栏 */}
      <div
        style={{
          position: 'sticky',
          bottom: 0,
          zIndex: 10,
          background: 'var(--sb-color-white)',
          borderTop: '1px solid var(--sb-color-border-secondary)',
          padding: '10px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <Button disabled={currentIdx === 0} onClick={goPrev} style={{ flex: '0 0 auto' }}>
          上一题
        </Button>
        <Button onClick={openAnswerCard} style={{ flex: 1 }}>
          答题卡 {answeredCount}/{total}
        </Button>
        {isLast ? (
          <Button
            type="primary"
            loading={submitting}
            onClick={handleSubmit}
            style={{ flex: '0 0 auto' }}
          >
            交卷
          </Button>
        ) : (
          <Button type="primary" onClick={goNext} style={{ flex: '0 0 auto' }}>
            下一题
          </Button>
        )}
      </div>

      {/* 答题卡抽屉 */}
      <Drawer
        title="答题卡"
        placement="bottom"
        open={cardOpen}
        onClose={() => setCardOpen(false)}
        height="auto"
        rootStyle={{ maxWidth: `min(100%, ${CONTENT_MAX_WIDTH}px)`, margin: '0 auto' }}
        styles={{
          wrapper: { maxHeight: '70vh' },
          content: { maxHeight: '70vh' },
          body: { padding: '12px 16px', overflowY: 'auto' },
          footer: { padding: '0 16px 16px', borderTop: 0 },
        }}
        footer={
          <Button type="primary" block loading={submitting} onClick={handleSubmit}>
            交卷
          </Button>
        }
      >
        <div
          data-testid="answer-card-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            gap: 8,
          }}
        >
          {questions.map((q, i) => {
            const answered = getAnswer(q.id).trim().length > 0;
            const marked = isMarked(q.id);
            const isCurrent = i === currentIdx;
            return (
              <button
                key={q.id}
                type="button"
                className="answer-card-item"
                aria-label={`第 ${i + 1} 题${answered ? '，已作答' : ''}${marked ? '，已标记' : ''}`}
                onClick={() => {
                  selectQuestion(i);
                  setCardOpen(false);
                }}
                style={{
                  width: '100%',
                  aspectRatio: '1 / 1',
                  padding: 0,
                  borderRadius: 8,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  fontSize: 15,
                  fontWeight: 500,
                  position: 'relative',
                  border: isCurrent
                    ? '2px solid var(--sb-color-primary)'
                    : '1px solid var(--sb-color-border-secondary)',
                  background: answered
                    ? 'var(--sb-color-primary)'
                    : isCurrent
                      ? 'var(--sb-color-bg-selected)'
                      : 'var(--sb-color-white)',
                  color: answered
                    ? 'var(--sb-color-white)'
                    : isCurrent
                      ? 'var(--sb-color-primary)'
                      : 'var(--sb-color-text-secondary)',
                }}
              >
                {i + 1}
                {marked && (
                  <StarFilled
                    style={{
                      position: 'absolute',
                      top: 2,
                      right: 2,
                      fontSize: 10,
                      color: 'var(--sb-color-warning)',
                    }}
                  />
                )}
              </button>
            );
          })}
        </div>
      </Drawer>

      <Modal
        open={confirmOpen}
        title="确认交卷"
        okText="确认交卷"
        cancelText="继续作答"
        okButtonProps={{ danger: true }}
        onOk={doSubmit}
        onCancel={() => setConfirmOpen(false)}
      >
        {exam
          ? `你已完成 ${answeredCount}/${exam.questions.length} 题。提交后将无法修改，确认交卷吗？`
          : ''}
      </Modal>
    </div>
  );
}

function formatTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

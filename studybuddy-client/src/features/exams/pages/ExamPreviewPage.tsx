/**
 * 试卷只读预览页（parent 用，问题5 修复）。
 *
 * parent 在试卷管理页点「预览」进入此页，只看题不答题。
 * 复用 GET /api/exam/{id}（get_current_user，两角色可用），不走答题 start/submit 流程，
 * 因此后端 require_student 不再拦截 parent。
 */

import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Typography, Button, Tag, Space, Empty } from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { examApi } from '@/features/exams/exam';
import type { ExamDetail, QuestionResponse } from '@/types';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Title, Text, Paragraph } = Typography;

const typeLabel: Record<string, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  transform: '转换题',
  translation: '翻译题',
  essay: '简答题',
  math_answer: '解答题',
};

export default function ExamPreviewPage() {
  const { examId } = useParams<{ examId: string }>();
  const navigate = useNavigate();
  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const id = Number(examId);
    if (!id) return;
    (async () => {
      try {
        const detail = await examApi.detail(id);
        setExam(detail);
      } catch (e) {
        setError((e as Error).message || '加载失败');
      } finally {
        setLoading(false);
      }
    })();
  }, [examId]);

  if (loading) {
    return (
      <PageSpinner />
    );
  }

  if (error || !exam) {
    return (
      <div style={{ padding: 40, maxWidth: READING_COLUMN_MAX, margin: '0 auto' }}>
        <Empty description={error || '试卷不存在'} />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button onClick={() => navigate(-1)}>返回</Button>
        </div>
      </div>
    );
  }

  const totalScore = exam.questions.reduce((s, q) => s + q.score, 0);

  return (
    <div className="exam-preview-page">
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(-1)}
        style={{ marginBottom: 16, padding: '4px 0' }}
      >
        返回
      </Button>

      {/* 试卷头 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ marginBottom: 8 }}>
          {exam.title}
        </Title>
        <Space size={8}>
          <Tag color="blue">{exam.questions.length} 题</Tag>
          <Tag>满分 {totalScore} 分</Tag>
          <Tag color="default">预览模式</Tag>
        </Space>
      </div>

      {/* 题目列表（只读，不显示作答控件） */}
      {exam.questions.map((q, i) => (
        <QuestionPreview key={q.id} question={q} index={i} />
      ))}
    </div>
  );
}

/** 单题只读展示：题干 + 选项 + 分值，不渲染作答控件 */
function QuestionPreview({ question, index }: { question: QuestionResponse; index: number }) {
  const q = question;
  const label = typeLabel[q.type] ?? q.type;
  const letters = q.options?.map((_, i) => String.fromCharCode(65 + i)) ?? [];

  return (
    <div
      className="exam-preview-question"
      style={{
        background: 'var(--sb-color-white)',
        border: '1px solid var(--sb-color-border-warm)',
        borderRadius: 12,
        marginBottom: 16,
      }}
    >
      {/* 题头：题号 + 题型 + 分值 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Text strong>第 {index + 1} 题</Text>
        <Tag color="default">{label}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {q.score} 分
        </Text>
      </div>

      {/* 题干 */}
      <Paragraph style={{ marginBottom: q.options?.length ? 12 : 0, whiteSpace: 'pre-wrap' }}>
        {q.stem}
      </Paragraph>

      {/* 选项（选择题才显示，只读不勾选） */}
      {q.options && q.options.length > 0 && (
        <div style={{ paddingLeft: 4 }}>
          {q.options.map((opt, i) => (
            <div key={i} style={{ marginBottom: 6, color: 'var(--sb-color-text)' }}>
              <Text strong style={{ marginRight: 8 }}>
                {letters[i]}.
              </Text>
              <Text>{opt}</Text>
            </div>
          ))}
        </div>
      )}

      {/* 提示：主观题/填空题答案不下发，预览不展示答案 */}
      {!q.options && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          作答区（预览不展示标准答案）
        </Text>
      )}
    </div>
  );
}

import { Radio, Checkbox, Input, Typography, Tag, Space } from 'antd';
import type { MouseEvent } from 'react';
import type { QuestionResponse } from '@/types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

const typeLabel: Record<string, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  transform: '转换题',
  translation: '翻译题',
  essay: '简答题',
  math_answer: '解答题',
};

interface Props {
  question: QuestionResponse;
  index: number;
  value: string;
  onChange: (answer: string) => void;
}

/**
 * 单题渲染组件 -- 根据题型渲染不同的作答控件。
 * value 是统一字符串：选择题存选项字母/数组，文字题存纯文本。
 */
export default function QuestionCard({ question, index, value, onChange }: Props) {
  const q = question;
  const label = typeLabel[q.type] ?? q.type;
  const usesTextAnswer = ['fill_blank', 'transform', 'translation', 'essay', 'math_answer'].includes(q.type);
  const blankMarkerCount = q.stem.match(/_{2,}|\.{2,}|…+/g)?.length ?? 0;
  const hasMultipleBlanks = usesTextAnswer && blankMarkerCount > 1;

  // 选择题选项：A/B/C/D... + 选项文本
  const renderOptions = (multi: boolean) => {
    if (!q.options || q.options.length === 0) return null;
    const letters = q.options.map((_, i) => String.fromCharCode(65 + i));

    // 手机端选项热区：整行可点、padding 放大、圆角
    const optionRowStyle = {
      padding: '10px 8px',
      borderRadius: 8,
      cursor: 'pointer' as const,
    };

    if (multi) {
      // 多选：value 是逗号分隔字母
      const checked = value ? value.split(',').filter(Boolean) : [];
      return (
        <Checkbox.Group
          value={checked}
          onChange={(vals) => onChange((vals as string[]).join(','))}
          style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
        >
          {q.options.map((opt, i) => (
            <div
              key={i}
              style={optionRowStyle}
              onMouseDown={(e: MouseEvent<HTMLDivElement>) => {
                e.preventDefault();
                const next = checked.includes(letters[i])
                  ? checked.filter((item) => item !== letters[i])
                  : [...checked, letters[i]];
                onChange(next.join(','));
              }}
            >
              <Checkbox value={letters[i]} style={{ alignItems: 'flex-start' }}>
                <Text style={{ whiteSpace: 'pre-wrap' }}>
                  <strong>{letters[i]}.</strong> {opt}
                </Text>
              </Checkbox>
            </div>
          ))}
        </Checkbox.Group>
      );
    }

    return (
      <Radio.Group
        value={value || undefined}
        onChange={(e) => onChange(e.target.value)}
        style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
      >
        {q.options.map((opt, i) => (
          <div
            key={i}
            style={optionRowStyle}
            onMouseDown={(e: MouseEvent<HTMLDivElement>) => {
              e.preventDefault();
              onChange(letters[i]);
            }}
          >
            <Radio value={letters[i]} style={{ alignItems: 'flex-start' }}>
              <Text style={{ whiteSpace: 'pre-wrap' }}>
                <strong>{letters[i]}.</strong> {opt}
              </Text>
            </Radio>
          </div>
        ))}
      </Radio.Group>
    );
  };

  return (
    <div style={{ padding: '16px 0', borderBottom: '1px solid var(--sb-color-border-subtle)' }}>
      {/* 题头 */}
      <Space size={8} style={{ marginBottom: 12 }}>
        <Tag color="blue" style={{ margin: 0 }}>
          第 {index + 1} 题
        </Tag>
        <Tag>{label}</Tag>
        <Text type="secondary" style={{ fontSize: 13 }}>
          {q.score} 分
        </Text>
      </Space>

      {/* 题干：长文本折叠，超 8 行显示「展开全文」 */}
      <Paragraph
        ellipsis={{ rows: 8, expandable: true, symbol: '展开全文' }}
        style={{ fontSize: 16, lineHeight: 1.7, marginBottom: 16, whiteSpace: 'pre-wrap' }}
      >
        {q.stem}
      </Paragraph>

      {/* 作答区 */}
      <div style={{ marginLeft: 4 }}>
        {q.type === 'single_choice' && renderOptions(false)}
        {q.type === 'multi_choice' && renderOptions(true)}
        {(q.type === 'fill_blank' ||
          q.type === 'transform' ||
          q.type === 'translation' ||
          q.type === 'essay' ||
          q.type === 'math_answer') && (
          <TextArea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={hasMultipleBlanks ? '多个空请按顺序用空格填写，如：Did visit' : '请在此作答…'}
            autoSize={{ minRows: q.type === 'essay' || q.type === 'math_answer' ? 6 : 3 }}
            style={{ fontSize: 15 }}
          />
        )}
      </div>
    </div>
  );
}

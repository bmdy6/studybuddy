import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Typography } from 'antd';
import {
  ToolOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';

import { MarkdownContent } from '@/shared/components/MarkdownContent';
import { repairLegacyMarkdown } from '@/shared/components/repairLegacyMarkdown';

const { Text } = Typography;

const MILLISECONDS_PER_SECOND = 1_000;
const SECONDS_PER_MINUTE = 60;
const TOOL_RESULT_PREVIEW_MAX_CHARS = 30;
const TOOL_PROGRESS_TICK_MS = 1_000;
const TOOL_OUTPUT_DETAIL_MAX_HEIGHT_PX = 200;


export interface ToolCard {
  id: string;
  name: string;
  input?: unknown;
  output?: string;
  status: 'running' | 'succeeded' | 'failed' | 'blocked' | 'timed_out' | 'done' | 'error';
  startedAt?: number;
  elapsedMs?: number;
  progress?: string;
}

export interface RenderMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  tools?: ToolCard[];
  /** 工具调用前的中间说明，工具轮结束时与最终回复去重合并。 */
  preToolContent?: string;
}

export function isInteractiveChoiceTool(tool: ToolCard): boolean {
  return tool.name === 'present_choice_question' || tool.name === 'present_profile_question';
}

export function choiceQuestionVisualSignature(tool: ToolCard): string | null {
  if (!isInteractiveChoiceTool(tool)) return null;
  const input = tool.input as { options?: Array<{ label?: unknown }> } | undefined;
  const labels = input?.options
    ?.map((option) => (typeof option.label === 'string' ? option.label.trim() : ''))
    .filter(Boolean);
  return labels?.length ? JSON.stringify(labels) : null;
}

const TOOL_LABELS: Record<string, string> = {
  create_exam: '出题',
  create_practice_exam: '自练卷',
  query_practice_exam_result: '读取练习结果',
  query_diagnosis: '查询学情',
  query_learning_map: '查询学习地图',
  query_error_book: '查询错题本',
  recommend_resource: '推荐资源',
  record_feedback: '记录反馈',
  create_study_plan: '创建计划',
  query_study_plans: '查询计划',
  save_note: '保存笔记',
  save_profile_onboarding: '保存画像',
  import_errors_process: '解析错题',
  import_errors_grade: '判分入错题本',
  grade_homework_photo: '拍题批改',
  save_graded_homework_errors: '保存批改错题',
  init_attributes: '初始化档案',
  get_attributes: '查看档案',
  present_profile_question: '选择',
  present_choice_question: '选择',
  update_profile: '更新画像',
};

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / MILLISECONDS_PER_SECOND));
  if (seconds < SECONDS_PER_MINUTE) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const rest = seconds % SECONDS_PER_MINUTE;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
}

/** 单条消息气泡 */
export function MessageBubble({
  msg,
}: {
  msg: RenderMessage;
}) {
  const isUser = msg.role === 'user';

  if (isUser) {
    // 空用户消息不显示气泡（冷启动自动触发用的空 content）
    if (!msg.content) return null;
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <div
          style={{
            background: 'var(--sb-color-primary)',
            color: 'var(--sb-color-white)',
            padding: '10px 16px',
            borderRadius: '12px 12px 4px 12px',
          }}
          className="sb-chat-bubble--user"
        >
          <Text style={{ color: 'var(--sb-color-white)', whiteSpace: 'pre-wrap' }}>
            {msg.content}
          </Text>
        </div>
      </div>
    );
  }

  const visibleTools = (() => {
    const seenChoiceQuestions = new Set<string>();
    return msg.tools?.filter((tool) => {
      if (!isInteractiveChoiceTool(tool)) return true;
      const signature = choiceQuestionVisualSignature(tool);
      if (!signature) return true;
      if (seenChoiceQuestions.has(signature)) return false;
      seenChoiceQuestions.add(signature);
      return true;
    });
  })();
  const hasRunningTool = visibleTools?.some((t) => t.status === 'running');
  const hasDoneTool = visibleTools?.some((t) => t.status === 'done');
  const showThinking = !msg.content && !hasRunningTool && !hasDoneTool;

  return (
    <div style={{ display: 'flex', marginBottom: 16 }}>
      <div className="sb-chat-bubble--assistant" style={{ width: '100%' }}>
        {visibleTools?.map((tool) => {
          if (tool.name === 'present_profile_question' || tool.name === 'present_choice_question') {
            // 选择按钮已停用：渲染成纯文字编号列表，AI 正文照常显示。
            const choiceInput = (tool.input ?? {}) as {
              question?: string;
              options?: Array<{ label: string; value: string }>;
            };
            const choiceOptions = choiceInput.options ?? [];
            return (
              <div
                key={tool.id}
                style={{
                  marginBottom: 8,
                  padding: '10px 16px',
                  background: 'var(--sb-color-bg-primary-soft)',
                  border: '1px solid var(--sb-color-border-primary-soft)',
                  borderRadius: '12px 12px 12px 4px',
                }}
              >
                {choiceOptions.length > 0 && (
                  <div style={{ fontSize: 14, lineHeight: 1.8, color: 'var(--sb-color-text)' }}>
                    {choiceOptions.map((opt, i) => (
                      <div key={opt.value}>{i + 1}. {opt.label}</div>
                    ))}
                  </div>
                )}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  回复数字或选项即可
                </Text>
              </div>
            );
          }
          // update_profile 为静默增量落库，不展示卡片，避免每条事实都冒卡片
          if (tool.name === 'update_profile') {
            return null;
          }
          if (tool.name === 'create_practice_exam') {
            return <PracticeExamCard key={tool.id} tool={tool} />;
          }
          return <ToolCallCard key={tool.id} tool={tool} />;
        })}
        {showThinking && (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: 'var(--sb-color-white)',
              border: '1px solid var(--sb-color-border-warm)',
              padding: '12px 16px',
              borderRadius: '12px 12px 12px 4px',
              boxShadow: '0 1px 2px var(--sb-shadow-message)',
            }}
          >
            <span style={{ fontSize: 12, color: 'var(--sb-color-text-tertiary)' }}>思考中</span>
            <ThinkingDots />
          </div>
        )}
        {msg.content && (
          <div
            style={{
              background: 'var(--sb-color-bg-primary-soft)',
              border: '1px solid var(--sb-color-border-primary-soft)',
              padding: '10px 16px',
              borderRadius: '12px 12px 12px 4px',
              boxShadow: '0 1px 2px var(--sb-shadow-message)',
            }}
          >
            <MarkdownContent content={repairLegacyMarkdown(msg.content)} />
          </div>
        )}
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 4 }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: 'var(--sb-color-text-tertiary)',
            display: 'inline-block',
            animation: `sb-thinking 1.2s ${i * 0.2}s infinite ease-in-out`,
          }}
        />
      ))}
      <style>{`
        @keyframes sb-thinking {
          0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
          30% { opacity: 1; transform: translateY(-3px); }
        }
      `}</style>
    </span>
  );
}



/** 折叠态摘要限长，超出加省略号；展开详情区展示完整 tool.output 不受此影响 */
function truncate(text: string, max = TOOL_RESULT_PREVIEW_MAX_CHARS): string {
  if (!text) return text;
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatToolResult(name: string, output: string): string {
  try {
    const result = JSON.parse(output);
    if (result.exam_id) return truncate(`试卷 #${result.exam_id} 已落库（${result.question_count}题）`);
    if (result.error) return truncate(`失败：${result.error}`);
    if (name === 'query_learning_map' && result.summary) {
      const summary = result.summary;
      return truncate(`优先补 ${summary.weak ?? 0} 个，巩固中 ${summary.reviewing ?? 0} 个，基本稳定 ${summary.stable ?? 0} 个`);
    }
    if (name === 'save_profile_onboarding' && result.saved)
      return truncate(`已保存学习画像（学生 #${result.id}）`);
    if (result.saved) return truncate(`已记录（#${result.id}）`);
    if (result.initialized) return truncate(`学习档案已初始化`);
    if (result.summary) return truncate(toDisplayText(result.summary));
    if (result.message) return truncate(toDisplayText(result.message));
    if (result.groups) return truncate(result.summary || `${result.groups.length} 组数据`);
    return truncate('已完成');
  } catch {
    return truncate(output);
  }
}

function toDisplayText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value == null) return '';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function PracticeExamCard({ tool }: { tool: ToolCard }) {
  const navigate = useNavigate();
  if (!['done', 'succeeded'].includes(tool.status) || !tool.output) {
    return <ToolCallCard tool={tool} />;
  }
  let data: { exam_id?: number; plan_item_id?: number | null; title?: string; question_count?: number } = {};
  try {
    data = JSON.parse(tool.output);
  } catch {
    return <ToolCallCard tool={tool} />;
  }
  if (!data.exam_id) {
    return <ToolCallCard tool={tool} />;
  }
  return (
    <div
      style={{
        background: 'var(--sb-color-bg-primary-soft)',
        borderLeft: '3px solid var(--sb-color-success-strong)',
        borderRadius: '0 8px 8px 0',
        marginBottom: 8,
        padding: '12px 14px',
        fontSize: 13,
        color: 'var(--sb-color-text-card)',
      }}
    >
      <div style={{ fontWeight: 500, marginBottom: 4 }}>自练卷已生成</div>
      <div style={{ fontSize: 12, color: 'var(--sb-color-text-soft)', marginBottom: 8 }}>
        {data.title} · {data.question_count} 题
      </div>
      <Button
        type="primary"
        size="large"
        icon={<CheckCircleOutlined />}
        onClick={() => {
          const path = `/exams/${data.exam_id}/take`;
          if (data.plan_item_id) {
            navigate(`${path}?plan_item_id=${data.plan_item_id}`);
          } else {
            navigate(path);
          }
        }}
      >
        开始作答
      </Button>
    </div>
  );
}

function ToolCallCard({ tool }: { tool: ToolCard }) {
  const label = TOOL_LABELS[tool.name] || tool.name;
  const isRunning = tool.status === 'running';
  const isFailed =
    tool.status === 'failed' || tool.status === 'blocked' || tool.status === 'timed_out' || tool.status === 'error';
  const isBlocked = tool.status === 'blocked';
  const [expanded, setExpanded] = useState(false);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!isRunning || !tool.startedAt) return undefined;
    const timer = window.setInterval(() => setTick((n) => n + 1), TOOL_PROGRESS_TICK_MS);
    return () => window.clearInterval(timer);
  }, [isRunning, tool.startedAt]);
  const elapsedMs =
    tool.elapsedMs ??
    (isRunning && tool.startedAt ? Math.max(0, Date.now() - tool.startedAt) : undefined);
  const summary =
    tool.output && (tool.status === 'done' || tool.status === 'succeeded')
      ? formatToolResult(tool.name, tool.output)
      : '';

  return (
    <div
      style={{
        background: 'var(--sb-color-bg-muted)',
        borderLeft: '3px solid var(--sb-color-tool-accent)',
        borderRadius: '0 8px 8px 0',
        marginBottom: 8,
        fontSize: 13,
        color: 'var(--sb-color-text-card)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          height: 40,
          padding: '0 12px',
          cursor: 'pointer',
          overflow: 'hidden',
          whiteSpace: 'nowrap',
        }}
        onClick={() => tool.output && setExpanded(!expanded)}
      >
        {isRunning ? (
          <LoadingOutlined style={{ color: 'var(--sb-color-tool-accent)', flexShrink: 0 }} />
        ) : isFailed ? (
          isBlocked ? (
            <WarningOutlined style={{ color: 'var(--sb-color-warning-deep)', flexShrink: 0 }} />
          ) : (
            <CloseCircleOutlined style={{ color: 'var(--sb-color-error-strong)', flexShrink: 0 }} />
          )
        ) : (
          <CheckCircleOutlined style={{ color: 'var(--sb-color-success-strong)', flexShrink: 0 }} />
        )}
        <ToolOutlined style={{ color: 'var(--sb-color-tool-accent)', flexShrink: 0 }} />
        <span style={{ fontWeight: 500, flexShrink: 0, whiteSpace: 'nowrap' }}>{label}</span>
        {isRunning && (
          <Text
            type="secondary"
            style={{
              fontSize: 12,
              flexShrink: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            正在执行{elapsedMs !== undefined ? `，已用 ${formatElapsed(elapsedMs)}` : ''}
          </Text>
        )}
        {isRunning && tool.progress && (
          <Text
            style={{
              fontSize: 12,
              color: 'var(--sb-color-text-soft)',
              flexShrink: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            - {tool.progress}
          </Text>
        )}
        {isFailed && tool.output && (
          <Text
            style={{
              fontSize: 12,
              color: isBlocked ? 'var(--sb-color-warning-deep)' : 'var(--sb-color-error-strong)',
              flexShrink: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            - {tool.output}
          </Text>
        )}
        {summary && (
          <Text
            style={{
              fontSize: 12,
              color: 'var(--sb-color-text-soft)',
              flexShrink: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            - {summary}
          </Text>
        )}
        {!isRunning && elapsedMs !== undefined && (
          <Text
            style={{
              fontSize: 11,
              color: 'var(--sb-color-text-tertiary)',
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            用时 {formatElapsed(elapsedMs)}
          </Text>
        )}
        {tool.output && !isRunning && (
          <Text
            style={{
              fontSize: 11,
              color: 'var(--sb-color-text-tertiary)',
              marginLeft: 'auto',
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            {expanded ? '收起' : '详情'}
          </Text>
        )}
      </div>
      {expanded && tool.output && (
        <pre
          style={{
            margin: 0,
            padding: '8px 12px',
            background: 'var(--sb-color-bg-tool-detail)',
            fontSize: 11,
            color: 'var(--sb-color-text-soft)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            maxHeight: TOOL_OUTPUT_DETAIL_MAX_HEIGHT_PX,
            overflowY: 'auto',
          }}
        >
          {(() => {
            try {
              return JSON.stringify(JSON.parse(tool.output), null, 2);
            } catch {
              return tool.output;
            }
          })()}
        </pre>
      )}
    </div>
  );
}

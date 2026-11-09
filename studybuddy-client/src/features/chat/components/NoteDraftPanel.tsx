import { useEffect, useState } from 'react';
import { Button, Input, Tag, Typography } from 'antd';
import { CheckOutlined, EditOutlined } from '@ant-design/icons';
import type { NoteDraftState } from '@/types';
import { MarkdownContent } from '@/shared/components/MarkdownContent';
import { READING_COLUMN_MAX } from '@/shared/theme/breakpoints';

const { Text } = Typography;
const { TextArea } = Input;

interface NoteDraftPanelProps {
  state: NoteDraftState;
  confirming?: boolean;
  /** 就这样存传 { status:'confirmed' }；改一下后传编辑后的字段 + status:'confirmed' */
  onConfirm: (edits: Partial<NoteDraftState>) => void;
}

/** 对话里的笔记草案卡：AI 整理好笔记后让弟弟确认/编辑，确认后才转 confirmed 正式笔记。 */
export function NoteDraftPanel({ state, confirming = false, onConfirm }: NoteDraftPanelProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(state.title);
  const [category, setCategory] = useState(state.category);
  const [content, setContent] = useState(state.content);

  useEffect(() => {
    setEditing(false);
    setTitle(state.title);
    setCategory(state.category);
    setContent(state.content);
  }, [state]);

  const cancelEdit = () => {
    setEditing(false);
    setTitle(state.title);
    setCategory(state.category);
    setContent(state.content);
  };

  return (
    <div
      className="sb-note-draft-panel"
      style={{
        maxWidth: READING_COLUMN_MAX,
        margin: '0 auto 12px',
        padding: 14,
        background: 'var(--sb-color-white)',
        border: '1px solid var(--sb-color-border-warm)',
        borderRadius: 8,
        boxShadow: '0 1px 2px var(--sb-shadow-message)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <div style={{ flex: 1 }}>
          <Text strong style={{ fontSize: 15 }}>
            我整理了一版笔记，你看看对不对
          </Text>
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              可以「就这样存」直接入库，或「改一下」再保存。确认后才会作为正式笔记被参考。
            </Text>
          </div>
        </div>
        <Tag color="warning" style={{ marginInlineEnd: 0 }}>
          待确认
        </Tag>
      </div>

      {editing ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="笔记标题" />
          <Input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="分类（如 语法/函数/古诗文）"
          />
          <TextArea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            autoSize={{ minRows: 6, maxRows: 16 }}
            placeholder="笔记正文（Markdown）"
          />
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Text strong style={{ fontSize: 15 }}>
              {state.title}
            </Text>
            {state.category ? <Tag color="blue">{state.category}</Tag> : null}
            <Tag>{state.subject}</Tag>
          </div>
          <div className="sb-note-draft-content" style={{ maxHeight: 320, overflow: 'auto' }}>
            <MarkdownContent content={state.content} />
          </div>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12, gap: 8 }}>
        {editing ? (
          <>
            <Button onClick={cancelEdit} disabled={confirming}>
              取消
            </Button>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={confirming}
              onClick={() => {
                setEditing(false);
                onConfirm({ title, category, content, status: 'confirmed' });
              }}
            >
              保存入库
            </Button>
          </>
        ) : (
          <>
            <Button icon={<EditOutlined />} onClick={() => setEditing(true)} disabled={confirming}>
              改一下
            </Button>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={confirming}
              onClick={() => onConfirm({ status: 'confirmed' })}
            >
              就这样存
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

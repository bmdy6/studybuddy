/**
 * 笔记详情页：Markdown 渲染 + 编辑（弟弟）/ 只读（家长）。
 */

import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Alert, App, Button, Card, Empty, Input, Skeleton, Tag, Typography } from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  DeleteOutlined,
  EditOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { noteApi } from '@/features/note/api';
import { useAuth } from '@/features/auth/useAuth';
import type { NoteItem } from '@/types';
import { MarkdownContent } from '@/shared/components/MarkdownContent';

const { Title, Text } = Typography;

export default function NoteDetailPage() {
  const { noteId } = useParams<{ noteId: string }>();
  const navigate = useNavigate();
  const { role } = useAuth();
  const { message } = App.useApp();
  const [note, setNote] = useState<NoteItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [relatedErrors, setRelatedErrors] = useState<
    { error_id: number; stem: string; error_count: number; last_wrong_at: string }[]
  >([]);

  const isParent = role === 'parent';

  const load = async () => {
    setLoading(true);
    setLoadError(false);
    setRelatedErrors([]);
    try {
      const n = await noteApi.get(Number(noteId));
      setNote(n);
      setEditContent(n.content);
      setEditTitle(n.title);
    } catch {
      setLoadError(true);
      setLoading(false);
      return;
    }
    try {
      const errs = await noteApi.relatedErrors(Number(noteId));
      setRelatedErrors(errs);
    } catch {
      setRelatedErrors([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [noteId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await noteApi.update(Number(noteId), {
        title: editTitle,
        content: editContent,
        status: 'confirmed',
      });
      setNote(updated);
      setEditing(false);
      message.success('已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await noteApi.delete(Number(noteId));
      message.success('已删除');
      navigate(-1);
    } catch {
      message.error('删除失败');
    }
  };

  if (loading)
    return (
      <div className="sb-note-detail-page sb-note-detail-loading">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  if (loadError)
    return (
      <div className="sb-note-detail-page">
        <Alert
          type="error"
          showIcon
          message="笔记暂时加载失败"
          description="请稍后重试，笔记内容不会被修改。"
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
              重试
            </Button>
          }
        />
      </div>
    );
  if (!note) return <Empty description="笔记不存在" style={{ padding: 60 }} />;

  return (
    <div className="sb-note-detail-page">
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(-1)}
        style={{ marginBottom: 16, padding: '4px 0' }}
      >
        返回笔记列表
      </Button>

      {/* 标题区 */}
      <div className="sb-note-detail-heading">
        {editing ? (
          <Input
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            style={{ fontSize: 20, fontWeight: 600, flex: 1 }}
          />
        ) : (
          <Title level={3} style={{ margin: 0 }}>
            {note.title}
          </Title>
        )}
        <Tag>{note.subject}</Tag>
        {note.status === 'draft' && <Tag className="sb-status-chip sb-status-chip--draft">待确认</Tag>}
        {note.status === 'confirmed' && (
          <Tag className="sb-status-chip sb-status-chip--confirmed">已确认</Tag>
        )}
      </div>

      {/* 标签 + 来源 */}
      <div className="sb-note-detail-meta">
        {note.knowledge_tags.map((t) => `#${t}`).join(' ')}
        {note.knowledge_tags.length > 0 && ' · '}
        来源：{note.source} · 更新于 {note.updated_at}
      </div>

      {/* 内容区 */}
      <Card className="sb-note-detail-content" style={{ borderRadius: 12 }}>
        {editing ? (
          <Input.TextArea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            autoSize={{ minRows: 15 }}
            style={{ fontFamily: 'monospace', fontSize: 13 }}
          />
        ) : (
          <MarkdownContent content={note.content} />
        )}
      </Card>

      {/* 关联错题：按知识点匹配的错题，弟弟能看到这个知识点错过哪些题 */}
      {relatedErrors.length > 0 && (
        <Card title="关联错题" style={{ marginTop: 16, borderRadius: 12 }} size="small">
          {relatedErrors.map((e) => (
            <div
              key={e.error_id}
              style={{ padding: '8px 0', borderBottom: '1px solid var(--sb-color-bg-muted)' }}
            >
              <Text>{e.stem}</Text>
              <div style={{ fontSize: 12, color: 'var(--sb-color-text-tertiary)', marginTop: 2 }}>
                错 {e.error_count} 次 · 最近 {e.last_wrong_at}
              </div>
            </div>
          ))}
        </Card>
      )}

      {/* 操作区 */}
      <div className="sb-note-detail-actions">
        {!isParent &&
          (editing ? (
            <>
              <Button type="primary" icon={<CheckOutlined />} loading={saving} onClick={handleSave}>
                保存
              </Button>
              <Button
                onClick={() => {
                  setEditing(false);
                  setEditContent(note.content);
                  setEditTitle(note.title);
                }}
              >
                取消
              </Button>
            </>
          ) : (
            <>
              <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>
                编辑
              </Button>
              {note.status === 'draft' && (
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  onClick={() => {
                    noteApi.update(Number(noteId), { status: 'confirmed' }).then((n) => {
                      setNote(n);
                      message.success('已确认');
                    });
                  }}
                >
                  确认笔记
                </Button>
              )}
              <Button danger icon={<DeleteOutlined />} onClick={handleDelete}>
                删除
              </Button>
            </>
          ))}
        {isParent && <Text type="secondary">家长只读</Text>}
      </div>
    </div>
  );
}

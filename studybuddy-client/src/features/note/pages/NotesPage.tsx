/**
 * 笔记列表页：学习记录 + 盲区聚合（concept 概念卡已废弃）。
 * 按 category 分类筛选；家长只读查看弟弟的笔记；弟弟可看自己的、可编辑/确认。
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Dropdown,
  Empty,
  List,
  Skeleton,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  BookOutlined,
  DownOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { noteApi } from '@/features/note/api';
import { useAuth } from '@/features/auth/useAuth';
import type { BlindSpotItem, NoteItem } from '@/types';

const { Text } = Typography;

const DAILY_REVIEW_FILTER = '__daily_review__';
const MAX_VISIBLE_CATEGORIES = 2;

function isDailyReview(note: NoteItem) {
  return note.category === '每日回顾' || note.source === '每日回顾';
}

export default function NotesPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // K2: 从知识路径/深链进入时按知识点过滤
  const tagFilter = searchParams.get('knowledge_tag') ?? null;
  const { role, activeChildId } = useAuth();
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [blindSpots, setBlindSpots] = useState<BlindSpotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  const studentId =
    role === 'parent' ? Number(searchParams.get('student_id')) || activeChildId || 2 : undefined;

  const load = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [noteList, spots] = await Promise.all([
        noteApi.list(studentId),
        noteApi.blindSpots(studentId),
      ]);
      setNotes(noteList);
      setBlindSpots(spots);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setActiveCategory(null);
    load();
  }, [studentId]); // eslint-disable-line react-hooks/exhaustive-deps

  const ordinaryNotes = useMemo(() => notes.filter((note) => !isDailyReview(note)), [notes]);
  const dailyReviewNotes = useMemo(() => notes.filter(isDailyReview), [notes]);

  // 高频分类保留在首屏，低频分类通过菜单访问，避免手机端筛选栏横向堆叠。
  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    ordinaryNotes.forEach((note) => {
      const category = note.category || '未分类';
      counts.set(category, (counts.get(category) || 0) + 1);
    });
    return Array.from(counts.entries())
      .sort(([nameA, countA], [nameB, countB]) => countB - countA || nameA.localeCompare(nameB))
      .map(([name]) => name);
  }, [ordinaryNotes]);

  const visibleCategories = categories.slice(0, MAX_VISIBLE_CATEGORIES);
  const extraCategories = categories.slice(MAX_VISIBLE_CATEGORIES);

  const filteredNotes = useMemo(() => {
    let source: NoteItem[];
    if (activeCategory === DAILY_REVIEW_FILTER) {
      source = dailyReviewNotes;
    } else {
      source = activeCategory
        ? ordinaryNotes.filter((note) => (note.category || '未分类') === activeCategory)
        : ordinaryNotes;
    }
    // K2: knowledge_tag 深链过滤（匹配笔记的知识点标签）
    if (tagFilter) {
      source = source.filter((note) => (note.knowledge_tags ?? []).includes(tagFilter));
    }
    return source;
  }, [activeCategory, dailyReviewNotes, ordinaryNotes, tagFilter]);

  const activeFilterLabel = activeCategory === DAILY_REVIEW_FILTER ? '历史回顾' : activeCategory;

  const setCategory = (category: string | null) => {
    setActiveCategory(category);
  };

  const filterItems = extraCategories.map((category) => ({
    key: category,
    label: category,
    onClick: () => setCategory(category),
  }));

  const showFilters = categories.length > 0 || dailyReviewNotes.length > 0;

  const categoryButton = (category: string, label = category) => (
    <Button
      key={category}
      type={activeCategory === category ? 'primary' : 'default'}
      size="small"
      onClick={() => setCategory(activeCategory === category ? null : category)}
    >
      {label}
    </Button>
  );

  const historyButton = dailyReviewNotes.length > 0 && (
    <Button
      type={activeCategory === DAILY_REVIEW_FILTER ? 'primary' : 'default'}
      size="small"
      onClick={() => setCategory(activeCategory === DAILY_REVIEW_FILTER ? null : DAILY_REVIEW_FILTER)}
    >
      历史回顾
    </Button>
  );

  const isParent = role === 'parent';

  const renderEmptyDescription = notes.length === 0 ? (
    <span>
      还没有笔记。
      <br />
      {isParent
        ? '弟弟学完知识点后，和助手对话时助手会帮整理笔记。'
        : '学完一个知识点后，在对话里让助手帮你整理笔记吧！'}
    </span>
  ) : ordinaryNotes.length === 0 && !activeCategory && dailyReviewNotes.length > 0 ? (
    <span>
      普通笔记暂时为空
      <br />
      可切换“历史回顾”查看以前的每日回顾。
    </span>
  ) : activeCategory === DAILY_REVIEW_FILTER ? (
    '还没有历史每日回顾'
  ) : (
    '该分类下没有笔记'
  );

  return (
    <StudentPageShell title="笔记" subtitle="学习记录与盲区" icon={<BookOutlined />}>

      {/* 盲区聚合：高频错题知识点 */}
      {blindSpots.length > 0 && (
        <Card
          title={
            <>
              <ExclamationCircleOutlined
                style={{ color: 'var(--sb-color-orange)', marginRight: 8 }}
              />
              我的盲区
            </>
          }
          style={{ marginBottom: 24, borderRadius: 12 }}
          size="small"
        >
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
            反复出错的知识点，建议重点复习或整理笔记
          </Text>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {blindSpots.map((s) => (
              <Tooltip key={s.tag} title={`错 ${s.error_count} 次，已有 ${s.note_count} 篇笔记`}>
                <Tag
                  color={s.error_count >= 5 ? 'red' : 'orange'}
                  style={{ cursor: 'default', padding: '4px 12px', fontSize: 13 }}
                >
                  {s.tag} · 错{s.error_count}次
                  {s.note_count > 0 && (
                    <span style={{ marginLeft: 4, opacity: 0.7 }}>笔记{s.note_count}</span>
                  )}
                </Tag>
              </Tooltip>
            ))}
          </div>
        </Card>
      )}

      {/* 分类筛选 */}
      {showFilters && (
        <div className="sb-notes-filters" aria-label="笔记筛选">
          <Button type={!activeCategory ? 'primary' : 'default'} size="small" onClick={() => setCategory(null)}>
            全部
          </Button>
          {visibleCategories.map((category) => categoryButton(category))}
          {extraCategories.length > 0 && (
            <Dropdown menu={{ items: filterItems }} trigger={['click']}>
              <Button size="small" aria-label="更多分类">
                更多分类 <DownOutlined />
              </Button>
            </Dropdown>
          )}
          {historyButton}
          {activeFilterLabel && activeCategory && !visibleCategories.includes(activeCategory) && activeCategory !== DAILY_REVIEW_FILTER && (
            <Tag className="sb-notes-active-filter">当前：{activeFilterLabel}</Tag>
          )}
        </div>
      )}

      {/* 笔记列表 */}
      <Card variant="borderless" style={{ borderRadius: 12 }} styles={{ body: { padding: 0 } }}>
        {loading ? (
          <div className="sb-notes-loading">
            <Skeleton active paragraph={{ rows: 4 }} />
          </div>
        ) : loadError ? (
          <Alert
            type="error"
            showIcon
            message="笔记暂时加载失败"
            description="请稍后重试，已有笔记不会被修改。"
            action={
              <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()} aria-label="重新加载笔记">
                重试
              </Button>
            }
            className="sb-notes-error"
          />
        ) : filteredNotes.length === 0 ? (
          <Empty
            image={
              <FileTextOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />
            }
            description={renderEmptyDescription}
            style={{ padding: '40px 0' }}
          />
        ) : (
          <List
            dataSource={filteredNotes}
            renderItem={(note) => (
              <List.Item
                className="sb-notes-item"
                onClick={() => navigate(`/notes/${note.id}`)}
                actions={[
                  <Button
                    key="view"
                    type="link"
                    size="small"
                    onClick={(event) => {
                      event.stopPropagation();
                      navigate(`/notes/${note.id}`);
                    }}
                  >
                    查看
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <FileTextOutlined
                      style={{ fontSize: 24, color: 'var(--sb-color-primary)', marginTop: 8 }}
                    />
                  }
                  title={
                    <div className="sb-notes-item-title">
                      <Text strong className="sb-notes-note-title">
                        {note.title}
                      </Text>
                      <Tag className="sb-notes-subject-tag">{note.subject}</Tag>
                      {note.category && <Tag className="sb-notes-category-tag">{note.category}</Tag>}
                      {note.status === 'draft' && (
                        <Tag className="sb-status-chip sb-status-chip--draft">待确认</Tag>
                      )}
                    </div>
                  }
                  description={
                    <div className="sb-notes-item-description">
                      <Text type="secondary" className="sb-notes-note-tags">
                        {note.knowledge_tags.map((t) => `#${t}`).join(' ') || '无标签'}
                      </Text>
                      <Text className="sb-notes-note-meta">
                        {note.updated_at}
                        {note.source ? ` · ${note.source}` : ''}
                      </Text>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>
    </StudentPageShell>
  );
}

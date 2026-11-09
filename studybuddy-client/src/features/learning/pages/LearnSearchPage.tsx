import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Input, List, Empty, Tag, Spin, Button } from 'antd';
import {
  SearchOutlined,
  BookOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  ProfileOutlined,
} from '@ant-design/icons';
import AppPageShell from '@/shared/components/AppPageShell';
import { noteApi } from '@/features/note/api';
import { errorBookApi } from '@/features/error_book/api';
import { examApi } from '@/features/exams/exam';
import { materialApi } from '@/features/materials/api';
import { useAuthStore } from '@/features/auth/store';
import { ROLES } from '@/shared/constants';

interface SearchResult {
  id: number;
  title: string;
  subject?: string;
  category?: string | null;
  detail: string;
  kind: 'note' | 'error' | 'exam' | 'material';
  link: string;
}

export default function LearnSearchPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const authState = useAuthStore();
  const { role, userId, activeChildId } = authState;
  const studentId = role === ROLES.PARENT ? activeChildId : userId;

  const [keyword, setKeyword] = useState(searchParams.get('q') ?? '');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [notes, setNotes] = useState<Array<{ id: number; title: string; subject: string; category?: string | null; content: string }>>([]);
  const [errors, setErrors] = useState<Array<{ error_id: number; stem: string; knowledge_tags: string[]; subject: string }>>([]);
  const [exams, setExams] = useState<Array<{ id: number; title: string; subject: string }>>([]);
  const [materials, setMaterials] = useState<Array<{ id: number; title: string; source?: string }>>([]);

  // 首次进入自动聚焦
  useEffect(() => {
    const el = document.querySelector<HTMLInputElement>('.sb-search-input input');
    el?.focus();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    setLoadError(false);
    const settled = await Promise.allSettled([
      noteApi.list(studentId ?? undefined),
      errorBookApi.list(studentId ?? undefined),
      examApi.list(),
      materialApi.list(),
    ]);
    const [noteRes, errRes, examRes, materialRes] = settled;
    // 单域失败只降级该域，不整页报错；全部失败才显示错误态
    setNotes(
      noteRes.status === 'fulfilled'
        ? noteRes.value.map((n) => ({
            id: n.id,
            title: n.title,
            subject: n.subject,
            category: n.category,
            content: n.content ?? '',
          }))
        : [],
    );
    if (errRes.status === 'fulfilled') {
      const flatErrors: Array<{ error_id: number; stem: string; knowledge_tags: string[]; subject: string }> = [];
      errRes.value.forEach((g) =>
        g.type_groups.forEach((tg) =>
          tg.questions.forEach((q) =>
            flatErrors.push({ error_id: q.error_id, stem: q.stem, knowledge_tags: q.knowledge_tags, subject: g.subject }),
          ),
        ),
      );
      setErrors(flatErrors);
    } else {
      setErrors([]);
    }
    setExams(
      examRes.status === 'fulfilled'
        ? examRes.value.map((e) => ({ id: e.id, title: e.title, subject: e.subject }))
        : [],
    );
    setMaterials(
      materialRes.status === 'fulfilled'
        ? materialRes.value.map((m) => ({ id: m.id, title: m.name, source: m.source }))
        : [],
    );
    if (settled.every((r) => r.status === 'rejected')) {
      setLoadError(true);
    }
    setLoading(false);
  };

  useEffect(() => {
    void loadAll();
  }, [studentId]); // eslint-disable-line react-hooks/exhaustive-deps

  const normalized = keyword.trim().toLowerCase();

  const results = useMemo<SearchResult[]>(() => {
    if (!normalized) return [];
    const hit = (text: string) => text.toLowerCase().includes(normalized);
    const out: SearchResult[] = [];
    notes
      .filter((n) => hit(n.title) || hit(n.content) || hit(n.subject ?? '') || hit(n.category ?? ''))
      .slice(0, 10)
      .forEach((n) =>
        out.push({
          id: n.id,
          title: n.title,
          subject: n.subject,
          category: n.category,
          detail: n.category ? `笔记 · ${n.category}` : '笔记',
          kind: 'note',
          link: `/notes/${n.id}`,
        }),
      );
    errors
      .filter((q) => hit(q.stem) || q.knowledge_tags.some(hit))
      .slice(0, 10)
      .forEach((q) =>
        out.push({
          id: q.error_id,
          title: q.stem.slice(0, 40),
          subject: q.subject,
          detail: `错题 · ${(q.knowledge_tags ?? []).slice(0, 3).join('、') || '待整理'}`,
          kind: 'error',
          link: '/error-book',
        }),
      );
    exams
      .filter((e) => hit(e.title) || hit(e.subject ?? ''))
      .slice(0, 5)
      .forEach((e) =>
        out.push({
          id: e.id,
          title: e.title,
          subject: e.subject,
          detail: '试卷',
          kind: 'exam',
          link: '/exams',
        }),
      );
    materials
      .filter((m) => hit(m.title) || hit(m.source ?? ''))
      .slice(0, 5)
      .forEach((m) =>
        out.push({
          id: m.id,
          title: m.title,
          subject: undefined,
          detail: '素材',
          kind: 'material',
          link: '/materials',
        }),
      );
    return out;
  }, [normalized, notes, errors, exams, materials]);

  const groupIcon = (kind: SearchResult['kind']) => {
    if (kind === 'note') return <BookOutlined />;
    if (kind === 'error') return <ProfileOutlined />;
    if (kind === 'exam') return <FileTextOutlined />;
    return <FolderOpenOutlined />;
  };

  return (
    <AppPageShell title="搜索学习内容" subtitle="搜错题、笔记、试卷和素材" icon={<SearchOutlined />}>
      <Input
        className="sb-search-input"
        size="large"
        allowClear
        autoFocus
        prefix={<SearchOutlined />}
        placeholder="输入关键词，如「一次函数」"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        onPressEnter={() => {
          if (keyword.trim()) navigate(`/search?q=${encodeURIComponent(keyword.trim())}`);
        }}
        style={{ marginBottom: 16 }}
      />
      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <Spin tip="正在加载学习内容…" />
        </div>
      ) : loadError ? (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <div>学习内容加载失败</div>
          <Button style={{ marginTop: 12 }} onClick={() => void loadAll()}>
            重新加载
          </Button>
        </div>
      ) : !normalized ? (
        <Empty description="输入关键词搜索错题、笔记、试卷和素材" style={{ padding: '48px 0' }} />
      ) : results.length === 0 ? (
        <Empty description={`没有找到与「${keyword.trim()}」相关的内容`} style={{ padding: '48px 0' }} />
      ) : (
        <List
          dataSource={results}
          renderItem={(item) => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() => navigate(item.link)}
              actions={[
                <Button key="go" type="link" size="small" onClick={(e) => { e.stopPropagation(); navigate(item.link); }}>
                  查看
                </Button>,
              ]}
            >
              <List.Item.Meta
                avatar={groupIcon(item.kind)}
                title={
                  <span>
                    {item.title}
                    {item.subject && (
                      <Tag style={{ marginLeft: 8 }} color="default">
                        {item.subject}
                      </Tag>
                    )}
                  </span>
                }
                description={item.detail}
              />
            </List.Item>
          )}
        />
      )}
    </AppPageShell>
  );
}

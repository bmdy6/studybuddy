import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Empty, Skeleton, Tag, Typography } from 'antd';
import { CalendarOutlined, CheckCircleOutlined, ClockCircleOutlined, HistoryOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { dailyRecordsApi } from '@/features/growth/dailyRecords';
import { noteApi } from '@/features/note/api';
import { getActiveStudentId, useAuthStore } from '@/features/auth/store';
import type { DailyLearningEvidence, DailyLearningRecord, NoteItem } from '@/types';

const { Text, Paragraph } = Typography;
const RANGE_DAYS = 30;
const MAX_EVIDENCE_PREVIEW = 3;

const TIER_LABELS: Record<DailyLearningEvidence['tier'], string> = {
  verified: '已验证',
  self_reported: '学生自报',
  machine_extracted: '机器识别',
};

function formatDate(value: string) {
  return dayjs(value).format('M月D日');
}

function sourceLabel(sourceType: string) {
  return ({
    exam_record: '作答/考试',
    error_book: '错题复练',
    note: '确认笔记',
    material: '学习素材',
    study_plan_item: '计划完成',
  } as Record<string, string>)[sourceType] ?? '学习记录';
}

function isNotFound(error: unknown) {
  return (error as { response?: { status?: number } })?.response?.status === 404;
}

export default function DailyRecordsPage() {
  const authState = useAuthStore();
  const studentId = getActiveStudentId(authState);
  const [records, setRecords] = useState<DailyLearningRecord[]>([]);
  const [history, setHistory] = useState<NoteItem[]>([]);
  const [selectedDate, setSelectedDate] = useState(() => dayjs().format('YYYY-MM-DD'));
  const [selectedRecord, setSelectedRecord] = useState<DailyLearningRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(false);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [detailEmpty, setDetailEmpty] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [evidenceExpanded, setEvidenceExpanded] = useState(false);
  const timelineRef = useRef<HTMLElement | null>(null);

  const load = useCallback(async () => {
    if (!studentId) {
      setLoading(false);
      setRecords([]);
      setHistory([]);
      setSelectedRecord(null);
      return;
    }
    setLoading(true);
    setError(false);
    setErrorStatus(null);
    const end = dayjs();
    const start = end.subtract(RANGE_DAYS - 1, 'day');
    try {
      const [items, notes] = await Promise.all([
        dailyRecordsApi.list(studentId, start.format('YYYY-MM-DD'), end.format('YYYY-MM-DD')),
        noteApi.list(studentId).catch(() => []),
      ]);
      const sorted = [...items].sort((a, b) => b.record_date.localeCompare(a.record_date));
      setRecords(sorted);
      setHistory(notes.filter((note) => note.category === '每日回顾' || note.source === '每日回顾').slice(0, 8));
      const initial = sorted[0] ?? null;
      setSelectedRecord(initial);
      setDetailEmpty(!initial);
      if (initial) setSelectedDate(initial.record_date);
    } catch (err) {
      setError(true);
      setErrorStatus((err as { response?: { status?: number } })?.response?.status ?? null);
    } finally {
      setLoading(false);
    }
  }, [studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectDate = async (value: string) => {
    setSelectedDate(value);
    setExpanded(false);
    setEvidenceExpanded(false);
    const cached = records.find((record) => record.record_date === value);
    if (cached) {
      setSelectedRecord(cached);
      setDetailEmpty(false);
    } else if (!studentId) {
      return;
    } else {
      setDetailLoading(true);
      try {
        const item = await dailyRecordsApi.getByDate(studentId, value);
        setSelectedRecord(item);
        setDetailEmpty(false);
      } catch (err) {
        if (isNotFound(err)) {
          setSelectedRecord(null);
          setDetailEmpty(true);
        } else {
          setError(true);
          setErrorStatus((err as { response?: { status?: number } })?.response?.status ?? null);
        }
      } finally {
        setDetailLoading(false);
      }
    }
    // 时间线自动滚动到选中日期
    requestAnimationFrame(() => {
      const container = timelineRef.current;
      if (!container) return;
      const active = container.querySelector('.sb-daily-records-day.is-active');
      active?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  };

  const summary = selectedRecord?.summary_text?.trim() || '今天暂时没有新的学习记录';
  const evidence = selectedRecord?.facts_snapshot.evidence ?? [];
  const pending = selectedRecord?.facts_snapshot.pending_tasks ?? [];
  const duration = selectedRecord?.facts_snapshot.self_reported_duration_minutes ?? 0;
  const durationLabel = duration > 0 ? `真实时长 ${duration} 分钟` : '真实时长未记录';
  const summaryText = expanded ? summary : summary.slice(0, 160);
  const canExpand = summary.length > 160;
  const selectedLabel = useMemo(() => formatDate(selectedDate), [selectedDate]);

  if (loading) {
    return <StudentPageShell title="每日学习记录" icon={<CalendarOutlined />}><Skeleton active paragraph={{ rows: 8 }} /></StudentPageShell>;
  }

  if (!studentId) {
    return <StudentPageShell title="每日学习记录" icon={<CalendarOutlined />}><Empty description="请先选择一个学生" /></StudentPageShell>;
  }

  if (error) {
    return (
      <StudentPageShell title="每日学习记录" icon={<CalendarOutlined />}>
        <Alert type="error" showIcon message={errorStatus === 403 ? '没有权限查看这位学生的学习记录' : '每日记录暂时加载失败'} description="请稍后重试，学习记录不会因此被修改。" action={<Button aria-label="重新加载" icon={<ReloadOutlined />} onClick={() => void load()}>重新加载</Button>} />
      </StudentPageShell>
    );
  }

  const evidencePreview = evidenceExpanded ? evidence : evidence.slice(0, MAX_EVIDENCE_PREVIEW);

  return (
    <StudentPageShell title="每日学习记录" subtitle="按日期查看自动整理的学习事实与摘要" icon={<CalendarOutlined />}>
      <div className="sb-daily-records-toolbar">
        <label htmlFor="daily-record-date">查看日期</label>
        <input id="daily-record-date" aria-label="选择日期" type="date" value={selectedDate} onChange={(event) => void selectDate(event.target.value)} />
        <Text type="secondary">只读展示，不会修改事实</Text>
      </div>

      {records.length === 0 && !selectedRecord ? (
        <Empty description="还没有自动学习记录" />
      ) : (
        <div className="sb-daily-records-layout">
          <nav ref={timelineRef} className="sb-daily-records-timeline" aria-label="每日记录时间线">
            {records.map((record) => (
              <button key={record.id} type="button" className={`sb-daily-records-day ${record.record_date === selectedDate ? 'is-active' : ''}`} onClick={() => void selectDate(record.record_date)}>
                <span>{formatDate(record.record_date)}</span>
                <Text ellipsis>{record.summary_text || '暂无摘要'}</Text>
              </button>
            ))}
          </nav>

          <section className="sb-daily-records-detail" aria-live="polite">
            {detailLoading ? <Skeleton active paragraph={{ rows: 5 }} /> : detailEmpty ? (
              <Empty description={`这一天还没有自动学习记录`} />
            ) : selectedRecord ? (
              <>
                <div className="sb-daily-records-detail-heading">
                  <div>
                    <Text className="sb-daily-records-date">{selectedLabel}</Text>
                    <Tag className="sb-daily-records-source-tag">{selectedRecord.summary_source === 'ai' ? 'AI 自动整理' : '事实摘要'}</Tag>
                  </div>
                  <Text type="secondary"><ClockCircleOutlined /> {durationLabel}</Text>
                </div>
                <div className="sb-daily-records-summary">
                  <Paragraph>{summaryText}{canExpand && !expanded ? '…' : ''}</Paragraph>
                  {canExpand && <Button type="link" onClick={() => setExpanded((value) => !value)}>{expanded ? '收起摘要' : '展开摘要'}</Button>}
                </div>
                <div className="sb-daily-records-section">
                  <Text strong>尚未完成</Text>
                  {pending.length === 0 ? <Text type="secondary"><CheckCircleOutlined /> 今天的记录里没有未完成项</Text> : pending.map((item, index) => (
                    <Text key={`${item.plan_title}-${item.item_title}-${index}`} className="sb-daily-records-pending"><ClockCircleOutlined /> {item.item_title}</Text>
                  ))}
                </div>
                <div className="sb-daily-records-section">
                  <Text strong>学习证据</Text>
                  {evidence.length === 0 ? <Text type="secondary">暂无可展示证据</Text> : (
                    <>
                      {evidencePreview.map((item) => (
                        <div className="sb-daily-records-evidence" key={`${item.source_type}-${item.source_id}-${item.version}`}>
                          <span className="sb-daily-records-evidence-title">{item.title || sourceLabel(item.source_type)}</span>
                          <Tag className="sb-daily-records-tier-tag">{TIER_LABELS[item.tier]}</Tag>
                        </div>
                      ))}
                      {evidence.length > MAX_EVIDENCE_PREVIEW && (
                        <Button type="link" size="small" onClick={() => setEvidenceExpanded((value) => !value)} style={{ alignSelf: 'flex-start' }}>
                          {evidenceExpanded ? '收起' : `展开全部 ${evidence.length} 条`}
                        </Button>
                      )}
                    </>
                  )}
                </div>
                {history.length > 0 && (
                  <details className="sb-daily-records-history">
                    <summary className="sb-daily-records-history-heading"><HistoryOutlined /><Text strong>历史回顾</Text><Text type="secondary">{history.length} 篇手写每日回顾</Text></summary>
                    <div>
                      {history.map((note) => (
                        <div key={note.id} className="sb-daily-records-history-item"><Text strong>{note.title}</Text><Text type="secondary">{note.content.replace(/\s+/g, ' ').slice(0, 120)}</Text></div>
                      ))}
                    </div>
                  </details>
                )}
              </>
            ) : null}
          </section>
        </div>
      )}
    </StudentPageShell>
  );
}

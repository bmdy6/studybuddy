import { useEffect, useMemo, useState } from 'react';
import dayjs from 'dayjs';
import {
  App,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Skeleton,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  SendOutlined,
  EyeOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { examApi } from '@/features/exams/exam';
import { useAuth } from '@/features/auth/useAuth';
import type { ExamAssignmentItem, ExamListItem } from '@/types';
import { SUBJECT_LABELS } from '@/shared/constants';
import AppPageShell from '@/shared/components/AppPageShell';

const { Text, Paragraph } = Typography;

export default function ExamManagePage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { children, role } = useAuth();
  const [exams, setExams] = useState<ExamListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [assigningExam, setAssigningExam] = useState<ExamListItem | null>(null);
  const [selectedStudentIds, setSelectedStudentIds] = useState<number[]>([]);
  const [assignmentNote, setAssignmentNote] = useState('');
  const [assignmentDueAt, setAssignmentDueAt] = useState<string | null>(null);
  const [existingAssignments, setExistingAssignments] = useState<ExamAssignmentItem[]>([]);
  const [assignmentLoading, setAssignmentLoading] = useState(false);
  const [assignmentSubmitting, setAssignmentSubmitting] = useState(false);
  const [assignmentLoadError, setAssignmentLoadError] = useState<string | null>(null);

  const loadExams = async () => {
    setLoading(true);
    try {
      const data = await examApi.list();
      setExams(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载试卷列表失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const statusTag: Record<string, { color: string; label: string }> = {
    published: { color: 'green', label: '已发布' },
    draft: { color: 'default', label: '草稿' },
    archived: { color: 'default', label: '已归档' },
    closed: { color: 'red', label: '已关闭' },
  };

  const filteredExams = useMemo(() => {
    const keyword = searchText.trim().toLowerCase();
    return exams.filter((exam) => {
      const matchKeyword = !keyword || exam.title.toLowerCase().includes(keyword);
      const matchStatus = !statusFilter || exam.status === statusFilter;
      return matchKeyword && matchStatus;
    });
  }, [exams, searchText, statusFilter]);

  const publishedCount = exams.filter((exam) => exam.status === 'published').length;
  const draftCount = exams.filter((exam) => exam.status === 'draft').length;
  const totalQuestions = exams.reduce((sum, exam) => sum + exam.question_count, 0);

  const openAssignModal = async (exam: ExamListItem) => {
    setAssigningExam(exam);
    setSelectedStudentIds([]);
    setAssignmentNote('');
    setAssignmentDueAt(null);
    setExistingAssignments([]);
    setAssignmentLoadError(null);
    setAssignmentLoading(true);
    try {
      const data = await examApi.assignments(exam.id);
      setExistingAssignments(data);
    } catch {
      setExistingAssignments([]);
      setAssignmentLoadError('分发记录加载失败');
      message.error('分发记录加载失败');
    } finally {
      setAssignmentLoading(false);
    }
  };

  const handleAssign = async () => {
    if (!assigningExam) return;
    if (selectedStudentIds.length === 0) {
      message.warning('请至少选择 1 位学生');
      return;
    }
    setAssignmentSubmitting(true);
    try {
      await examApi.assign(assigningExam.id, {
        student_ids: selectedStudentIds,
        due_at: assignmentDueAt,
        note: assignmentNote.trim() || null,
      });
      message.success(`已分发给 ${selectedStudentIds.length} 位学生`);
      setAssigningExam(null);
      await loadExams();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '分发试卷失败';
      message.error(msg);
    } finally {
      setAssignmentSubmitting(false);
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string) => <Text strong>{title}</Text>,
    },
    {
      title: '科目',
      dataIndex: 'subject',
      key: 'subject',
      width: 90,
      render: (subject: string) => SUBJECT_LABELS[subject] ?? subject,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const s = statusTag[status] ?? { color: 'default', label: status };
        return <Tag color={s.color}>{s.label}</Tag>;
      },
    },
    {
      title: '题数',
      dataIndex: 'question_count',
      key: 'question_count',
      width: 70,
    },
    {
      title: '满分',
      dataIndex: 'total_score',
      key: 'total_score',
      width: 70,
      render: (v: number) => `${v} 分`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (v: string) => v.slice(0, 10),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: unknown, record: ExamListItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/exams/${record.id}/preview`)}
          >
            预览
          </Button>
          {role === 'parent' && record.status === 'published' && children.length > 0 && (
            <Button
              type="link"
              size="small"
              icon={<SendOutlined />}
              onClick={() => void openAssignModal(record)}
            >
              分发
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <AppPageShell
      title="试卷管理"
      subtitle="管理 Agent 生成的试卷；发布后学生才能开始练习。"
      icon={<FileTextOutlined />}
      actions={
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={loadExams} loading={loading}>
            刷新
          </Button>
        </Space>
      }
      metrics={[
        { label: '试卷总数', value: exams.length, hint: `当前显示 ${filteredExams.length} 套` },
        { label: '已发布', value: publishedCount, hint: '学生可见可练习', tone: 'success' },
        { label: '草稿', value: draftCount, hint: '发布前仅家长可见', tone: draftCount ? 'warning' : 'default' },
        { label: '题目总量', value: `${totalQuestions} 题`, hint: '已导入题目' },
      ]}
      maxWidth={1100}
    >
      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: 0 } }}>
        <div className="sb-table-toolbar">
          <div className="sb-toolbar-filters">
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索试卷标题"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: 240 }}
            />
            <Select
              allowClear
              placeholder="状态"
              value={statusFilter}
              onChange={setStatusFilter}
              style={{ width: 128 }}
              options={[
                { value: 'draft', label: '草稿' },
                { value: 'published', label: '已发布' },
                { value: 'archived', label: '已归档' },
                { value: 'closed', label: '已关闭' },
              ]}
            />
          </div>
          <Text type="secondary" style={{ fontSize: 13 }}>
            当前显示 {filteredExams.length} 套
          </Text>
        </div>
        {loading ? (
          <div className="sb-table-loading">
            <Skeleton active paragraph={{ rows: 6 }} />
          </div>
        ) : (
          <Table
            columns={columns}
            dataSource={filteredExams}
            rowKey="id"
            size="middle"
            pagination={{ pageSize: 15, showSizeChanger: true }}
            locale={{
              emptyText: (
                <Empty
                  image={
                    <FileTextOutlined
                      style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }}
                    />
                  }
                  description={
                    searchText || statusFilter
                      ? '没有匹配的试卷，调整搜索或状态筛选'
                      : '还没有试卷，在对话里让 AI 出题后即可发布给学生练习'
                  }
                  style={{ padding: '40px 0' }}
                >
                </Empty>
              ),
            }}
          />
        )}
      </Card>
      <Modal
        title={assigningExam ? `分发：${assigningExam.title}` : '分发试卷'}
        open={!!assigningExam}
        onCancel={() => setAssigningExam(null)}
        onOk={() => void handleAssign()}
        okText="确认分发"
        cancelText="取消"
        confirmLoading={assignmentSubmitting}
        destroyOnHidden
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div>
            <Text strong>选择学生</Text>
            <div style={{ marginTop: 12 }}>
              <Checkbox.Group
                value={selectedStudentIds}
                onChange={(values) => setSelectedStudentIds(values as number[])}
                style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              >
                {children.map((child) => (
                  <Checkbox key={child.id} value={child.id}>
                    {child.display_name}
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </div>
          </div>

          <div>
            <Text strong>截止时间</Text>
            <DatePicker
              showTime
              allowClear
              style={{ width: '100%', marginTop: 12 }}
              value={assignmentDueAt ? dayjs(assignmentDueAt) : null}
              onChange={(value) =>
                setAssignmentDueAt(value ? value.format('YYYY-MM-DD HH:mm:ss') : null)
              }
            />
          </div>

          <div>
            <Text strong>备注</Text>
            <Input.TextArea
              rows={3}
              maxLength={120}
              showCount
              placeholder="例如：周五前完成，做完一起复盘。"
              value={assignmentNote}
              onChange={(e) => setAssignmentNote(e.target.value)}
              style={{ marginTop: 12 }}
            />
          </div>

          {assignmentLoading ? (
            <Skeleton active paragraph={{ rows: 2 }} />
          ) : assignmentLoadError ? (
            <Text type="secondary">{assignmentLoadError}</Text>
          ) : existingAssignments.length > 0 ? (
            <div>
              <Text strong>已分发记录</Text>
              <div style={{ marginTop: 12 }}>
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {existingAssignments.map((item) => (
                    <Card key={item.id} size="small" style={{ borderRadius: 8 }}>
                      <Space direction="vertical" size={4}>
                        <Text>{item.student_name}</Text>
                        <Text type="secondary">
                          {item.due_at ? `截止 ${item.due_at}` : '未设置截止时间'}
                        </Text>
                        {item.note && (
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            {item.note}
                          </Paragraph>
                        )}
                      </Space>
                    </Card>
                  ))}
                </Space>
              </div>
            </div>
          ) : null}
        </Space>
      </Modal>
    </AppPageShell>
  );
}

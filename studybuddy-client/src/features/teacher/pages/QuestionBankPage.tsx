import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd';
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  InboxOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  StopOutlined,
  ToolOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type { UploadFile, UploadProps } from 'antd';
import { questionBankApi } from '@/features/teacher/questionBank';
import AppPageShell from '@/shared/components/AppPageShell';
import type {
  CreatePaperSourceRequest,
  PaperSourceFullPreviewResponse,
  QuestionBankItem,
  QuestionBankPaperItem,
  QuestionBankPaperStatus,
  QuestionBankReviewMetrics,
  SearchPaperSourcesRequest,
} from '@/types';
import {
  ADAPTER_META,
  DEFAULT_SEARCH,
  ITEM_STATUS_META,
  REVIEW_META,
  RISK_META,
  SOURCE_ADAPTER_OPTIONS,
  STATUS_META,
  formatRate,
} from '@/features/teacher/questionBankMeta';

const { Paragraph, Text } = Typography;
const { Dragger } = Upload;

type UploadPaperSourceFormValues = Omit<SearchPaperSourcesRequest, 'limit'> & {
  title?: string;
};

export default function QuestionBankPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<SearchPaperSourcesRequest>();
  const [manualForm] = Form.useForm<CreatePaperSourceRequest>();
  const [uploadForm] = Form.useForm<UploadPaperSourceFormValues>();
  const [papers, setPapers] = useState<QuestionBankPaperItem[]>([]);
  const [items, setItems] = useState<QuestionBankItem[]>([]);
  const [reviewMetrics, setReviewMetrics] = useState<QuestionBankReviewMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [uploadSubmitting, setUploadSubmitting] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [statusFilter, setStatusFilter] = useState<QuestionBankPaperStatus | undefined>();
  const [subjectFilter, setSubjectFilter] = useState<string | undefined>();
  const [sourceKeyword, setSourceKeyword] = useState('');
  const [itemKeyword, setItemKeyword] = useState('');
  const [reviewingIds, setReviewingIds] = useState<Set<number>>(new Set());
  const [parsingIds, setParsingIds] = useState<Set<number>>(new Set());
  const [previewingId, setPreviewingId] = useState<number | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [paperPreview, setPaperPreview] = useState<PaperSourceFullPreviewResponse | null>(null);
  const [itemStatusFilter, setItemStatusFilter] = useState<string>('pending');

  const loadPapers = async () => {
    setLoading(true);
    try {
      const data = await questionBankApi.listPaperSources({
        status: statusFilter,
        subject: subjectFilter,
        keyword: sourceKeyword.trim() || undefined,
        limit: 80,
      });
      setPapers(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载试卷来源失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateManualSource = async () => {
    const values = await manualForm.validateFields();
    setManualSubmitting(true);
    try {
      const payload: CreatePaperSourceRequest = {
        ...values,
        province: values.province || DEFAULT_SEARCH.province,
        city: values.city || DEFAULT_SEARCH.city,
        district: values.district || DEFAULT_SEARCH.district,
        school: values.school || DEFAULT_SEARCH.school,
      };
      const created = await questionBankApi.createPaperSource(payload);
      setPapers((items) => [created, ...items.filter((item) => item.id !== created.id)]);
      void loadReviewMetrics();
      message.success('已加入来源库');
      manualForm.resetFields(['title', 'source_url', 'snippet']);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加入来源库失败';
      message.error(msg);
    } finally {
      setManualSubmitting(false);
    }
  };

  const handleUploadPaperSource = async () => {
    const values = await uploadForm.validateFields();
    if (!uploadFile) {
      message.warning('请先选择 PDF、TXT 或 HTML 试卷文件');
      return;
    }
    setUploadSubmitting(true);
    try {
      const uploaded = await questionBankApi.uploadPaperSource({
        ...values,
        file: uploadFile,
        title: values.title || uploadFile.name,
        province: values.province || DEFAULT_SEARCH.province,
        city: values.city || DEFAULT_SEARCH.city,
        district: values.district || DEFAULT_SEARCH.district,
        school: values.school || DEFAULT_SEARCH.school,
      });
      setPapers((items) => [uploaded.paper, ...items.filter((item) => item.id !== uploaded.paper.id)]);
      void loadReviewMetrics();
      const validation = uploaded.validation;
      const answerHint = validation.has_answer_signal ? '有答案信号' : '答案待确认';
      message.success(`已加入候选：约 ${validation.question_count_estimate} 题，${answerHint}`);
      setUploadFile(null);
      uploadForm.resetFields(['title']);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '上传试卷失败';
      message.error(msg);
    } finally {
      setUploadSubmitting(false);
    }
  };

  const loadItems = async () => {
    setItemsLoading(true);
    try {
      const data = await questionBankApi.listItems({
        status: itemStatusFilter,
        subject: subjectFilter,
        keyword: itemKeyword.trim() || undefined,
        limit: 80,
      });
      setItems(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载待确认题目失败';
      message.error(msg);
    } finally {
      setItemsLoading(false);
    }
  };

  const loadReviewMetrics = async () => {
    setMetricsLoading(true);
    try {
      const data = await questionBankApi.getReviewMetrics();
      setReviewMetrics(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载初审统计失败';
      message.error(msg);
    } finally {
      setMetricsLoading(false);
    }
  };

  useEffect(() => {
    loadPapers();
    loadReviewMetrics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, subjectFilter]);

  useEffect(() => {
    loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemStatusFilter, subjectFilter]);

  const handleSearch = async () => {
    const values = await form.validateFields();
    setSearching(true);
    try {
      const res = await questionBankApi.searchPaperSources(values);
      message.success(`已保存 ${res.saved_count} 个试卷来源`);
      setPapers(res.candidates);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '搜索候选来源失败';
      message.error(msg);
    } finally {
      setSearching(false);
    }
  };

  const updateStatus = async (paper: QuestionBankPaperItem, status: QuestionBankPaperStatus) => {
    try {
      const updated = await questionBankApi.updatePaperSourceStatus(paper.id, status);
      setPapers((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      void loadReviewMetrics();
      message.success(STATUS_META[status].label);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '更新候选状态失败';
      message.error(msg);
    }
  };

  const reviewPaper = async (paper: QuestionBankPaperItem) => {
    setReviewingIds((ids) => new Set(ids).add(paper.id));
    try {
      const updated = await questionBankApi.reviewPaperSource(paper.id);
      setPapers((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      void loadReviewMetrics();
      const meta = updated.review ? REVIEW_META[updated.review.verdict] : undefined;
      message.success(meta ? `初审完成：${meta.label}` : '初审完成');
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '初审失败';
      message.error(msg);
    } finally {
      setReviewingIds((ids) => {
        const next = new Set(ids);
        next.delete(paper.id);
        return next;
      });
    }
  };

  const parsePaper = async (paper: QuestionBankPaperItem) => {
    setParsingIds((ids) => new Set(ids).add(paper.id));
    try {
      const result = await questionBankApi.parsePaperSource(paper.id);
      const warning = result.warnings.length ? `；${result.warnings[0]}` : '';
      message.success(`解析出 ${result.parsed_count} 道，新增 ${result.saved_count} 道待确认题目${warning}`);
      void loadItems();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '解析入库失败';
      message.error(msg);
    } finally {
      setParsingIds((ids) => {
        const next = new Set(ids);
        next.delete(paper.id);
        return next;
      });
    }
  };

  const previewPaper = async (paper: QuestionBankPaperItem) => {
    setPreviewingId(paper.id);
    try {
      const preview = await questionBankApi.getPaperSourceFullPreview(paper.id);
      setPaperPreview(preview);
      setPreviewOpen(true);
      if (preview.status === 'login_required') {
        message.warning('这个来源需要登录后才能拿到整卷');
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '获取试卷预览失败';
      message.error(msg);
    } finally {
      setPreviewingId(null);
    }
  };

  const topSummary = useMemo(() => {
    const confirmed = papers.filter((p) => p.status === 'confirmed').length;
    const candidates = papers.filter((p) => p.status === 'candidate').length;
    const styleOnly = papers.filter((p) => p.status === 'internal_style').length;
    return { confirmed, candidates, styleOnly };
  }, [papers]);

  const updateItemStatus = async (item: QuestionBankItem, status: 'approved' | 'rejected') => {
    try {
      const updated = await questionBankApi.updateItemStatus(item.id, status);
      setItems((list) => list.map((entry) => (entry.id === item.id ? updated : entry)));
      message.success(ITEM_STATUS_META[status].label);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '更新题目状态失败';
      message.error(msg);
    }
  };

  const uploadList: UploadFile[] = uploadFile
    ? [
        {
          uid: 'question-bank-upload',
          name: uploadFile.name,
          status: 'done',
        },
      ]
    : [];

  const uploadProps: UploadProps = {
    accept: '.pdf,.txt,.html,.htm',
    maxCount: 1,
    fileList: uploadList,
    beforeUpload: (file) => {
      setUploadFile(file);
      if (!uploadForm.getFieldValue('title')) {
        uploadForm.setFieldValue('title', file.name.replace(/\.[^.]+$/, ''));
      }
      return false;
    },
    onRemove: () => {
      setUploadFile(null);
    },
  };

  const columns = [
    {
      title: '候选来源',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, record: QuestionBankPaperItem) => (
        <Space direction="vertical" size={4}>
          <Text strong>{title}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {[
              record.province,
              record.city,
              record.district,
              record.grade,
              record.semester,
              record.subject,
            ]
              .filter(Boolean)
              .join(' / ')}
          </Text>
          {record.snippet && (
            <Paragraph
              type="secondary"
              ellipsis={{ rows: 2, tooltip: record.snippet }}
              style={{ maxWidth: 520, marginBottom: 0, fontSize: 12 }}
            >
              {record.snippet}
            </Paragraph>
          )}
        </Space>
      ),
    },
    {
      title: '完整性',
      key: 'completeness',
      width: 160,
      render: (_: unknown, record: QuestionBankPaperItem) => {
        const review = record.review;
        if (!review) {
          return (
            <Space direction="vertical" size={2}>
              <Tag color="default">未初审</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                待完整性校验
              </Text>
            </Space>
          );
        }
        const meta = REVIEW_META[review.verdict] ?? { color: 'default', label: review.verdict };
        const count = review.evidence.question_count_estimate ?? 0;
        const answer = review.evidence.has_answer_signal ? '有答案信号' : '答案待确认';
        return (
          <Space direction="vertical" size={2}>
            <Tag color={meta.color}>{meta.label}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {count ? `约 ${count} 题 · ${answer}` : answer}
            </Text>
          </Space>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 96,
      render: (status: QuestionBankPaperStatus) => {
        const meta = STATUS_META[status];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 90,
      render: (risk: string) => {
        const meta = RISK_META[risk] ?? { color: 'default', label: risk };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: '来源',
      dataIndex: 'source_adapter',
      key: 'source_adapter',
      width: 96,
      render: (adapter: string | null) => {
        const meta = adapter ? ADAPTER_META[adapter] ?? { color: 'default', label: adapter } : undefined;
        return meta ? <Tag color={meta.color}>{meta.label}</Tag> : <Tag>未知</Tag>;
      },
    },
    {
      title: '等级',
      dataIndex: 'availability_level',
      key: 'availability_level',
      width: 70,
      render: (level: string) => <Tag>{level}</Tag>,
    },
    {
      title: '匹配',
      dataIndex: 'confidence',
      key: 'confidence',
      width: 80,
      render: (confidence: number) => `${confidence}%`,
      sorter: (a: QuestionBankPaperItem, b: QuestionBankPaperItem) => a.confidence - b.confidence,
    },
    {
      title: '操作',
      key: 'actions',
      width: 260,
      render: (_: unknown, record: QuestionBankPaperItem) => (
        <Space size={4} wrap>
          <Tooltip title="打开来源">
            <Button
              size="small"
              icon={<LinkOutlined />}
              disabled={record.source_url.startsWith('upload://')}
              onClick={() => window.open(record.source_url, '_blank', 'noopener,noreferrer')}
            />
          </Tooltip>
          <Button
            size="small"
            icon={<FileSearchOutlined />}
            loading={previewingId === record.id}
            onClick={() => previewPaper(record)}
          >
            看试卷
          </Button>
          <Button
            size="small"
            icon={<ToolOutlined />}
            loading={reviewingIds.has(record.id)}
            onClick={() => reviewPaper(record)}
          >
            初审
          </Button>
          <Button
            size="small"
            loading={parsingIds.has(record.id)}
            disabled={record.review?.verdict === 'reject' || record.review?.verdict === 'style_only'}
            onClick={() => parsePaper(record)}
          >
            解析
          </Button>
          <Button
            size="small"
            icon={<CheckCircleOutlined />}
            onClick={() => updateStatus(record, 'confirmed')}
          >
            可信
          </Button>
          <Button
            size="small"
            icon={<ToolOutlined />}
            onClick={() => updateStatus(record, 'internal_style')}
          >
            风格
          </Button>
          <Button
            size="small"
            icon={<StopOutlined />}
            onClick={() => updateStatus(record, 'rejected')}
          >
            拒绝
          </Button>
        </Space>
      ),
    },
  ];

  const itemColumns = [
    {
      title: '题目',
      dataIndex: 'stem',
      key: 'stem',
      render: (stem: string, record: QuestionBankItem) => (
        <Space direction="vertical" size={4}>
          <Paragraph ellipsis={{ rows: 2, tooltip: stem }} style={{ maxWidth: 620, marginBottom: 0 }}>
            {stem}
          </Paragraph>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {[record.grade, record.semester, record.subject, record.question_type].filter(Boolean).join(' / ')}
          </Text>
          {record.answer && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              答案：{record.answer}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => {
        const meta = ITEM_STATUS_META[status] ?? { color: 'default', label: status };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: QuestionBankItem) => (
        <Space size={4}>
          <Button size="small" icon={<CheckCircleOutlined />} onClick={() => updateItemStatus(record, 'approved')}>
            通过
          </Button>
          <Button size="small" icon={<StopOutlined />} onClick={() => updateItemStatus(record, 'rejected')}>
            拒绝
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <AppPageShell
      title="试卷来源库"
      subtitle="八上优先采集，七下作为补漏；先确认来源完整，再解析整卷进入题库审核。"
      icon={<DatabaseOutlined />}
      actions={
        <Space wrap>
          <Tag color="green">可信 {topSummary.confirmed}</Tag>
          <Tag color="processing">待确认 {topSummary.candidates}</Tag>
          <Tag color="gold">风格 {topSummary.styleOnly}</Tag>
        </Space>
      }
      metrics={[
        {
          label: '人工抽样',
          value: metricsLoading || !reviewMetrics ? '-' : `${reviewMetrics.sampled_count}/${reviewMetrics.total_reviewed}`,
          hint: `门禁样本 ${reviewMetrics?.min_sample_size ?? 20} 条`,
        },
        {
          label: '整体一致率',
          value: metricsLoading || !reviewMetrics ? '-' : formatRate(reviewMetrics.agreement_rate),
          hint: 'AI 建议与人工状态一致',
          tone: reviewMetrics?.agreement_rate && reviewMetrics.agreement_rate >= 0.8 ? 'success' : 'default',
        },
        {
          label: '可入库误判率',
          value: metricsLoading || !reviewMetrics ? '-' : formatRate(reviewMetrics.formal_ready_false_positive_rate),
          hint: `上限 ${reviewMetrics ? formatRate(reviewMetrics.max_formal_ready_false_positive_rate) : '10%'}`,
          tone:
            reviewMetrics?.formal_ready_false_positive_rate !== null &&
            reviewMetrics?.formal_ready_false_positive_rate !== undefined &&
            reviewMetrics.formal_ready_false_positive_rate > reviewMetrics.max_formal_ready_false_positive_rate
              ? 'danger'
              : 'default',
        },
        {
          label: '自动入库门禁',
          value: reviewMetrics?.auto_approve_allowed ? '允许低风险' : '继续复核',
          hint: '当前仍保留人工抽样',
          tone: reviewMetrics?.auto_approve_allowed ? 'success' : 'warning',
        },
      ]}
    >

      <Alert
        type="info"
        showIcon
        className="sb-page-alert"
        message="上方是试卷来源，下方是解析出的待审核题目"
        description="试卷来源需要先检查是否完整，再解析成待审核题目；人工通过后才会进入正式题库，避免只拿到预览页前几题就误入库。"
      />

      <Card style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form form={form} layout="vertical" initialValues={DEFAULT_SEARCH}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: 12,
            }}
          >
            <Form.Item name="district" label="区县" style={{ marginBottom: 0 }}>
              <Input />
            </Form.Item>
            <Form.Item name="school" label="学校" style={{ marginBottom: 0 }}>
              <Input />
            </Form.Item>
            <Form.Item
              name="grade"
              label="年级"
              rules={[{ required: true }]}
              style={{ marginBottom: 0 }}
            >
              <Select
                options={[
                  { value: '八年级', label: '八年级' },
                  { value: '七年级', label: '七年级' },
                ]}
              />
            </Form.Item>
            <Form.Item name="semester" label="册次" style={{ marginBottom: 0 }}>
              <Select
                options={[
                  { value: '上册', label: '上册' },
                  { value: '下册', label: '下册' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="subject"
              label="学科"
              rules={[{ required: true }]}
              style={{ marginBottom: 0 }}
            >
              <Select
                options={[
                  { value: '数学', label: '数学' },
                  { value: '英语', label: '英语' },
                  { value: '语文', label: '语文' },
                ]}
              />
            </Form.Item>
            <Form.Item name="exam_type" label="考试类型" style={{ marginBottom: 0 }}>
              <Select
                options={[
                  { value: '期中', label: '期中' },
                  { value: '期末', label: '期末' },
                  { value: '月考', label: '月考' },
                ]}
              />
            </Form.Item>
            <Form.Item name="limit" label="候选数" style={{ marginBottom: 0 }}>
              <Select
                options={[
                  { value: 5, label: '5' },
                  { value: 8, label: '8' },
                  { value: 12, label: '12' },
                ]}
              />
            </Form.Item>
            <Form.Item label=" " style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                icon={<SearchOutlined />}
                loading={searching}
                onClick={handleSearch}
                block
              >
                搜索候选
              </Button>
            </Form.Item>
          </div>
          <Form.Item name="province" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="city" hidden>
            <Input />
          </Form.Item>
        </Form>
      </Card>

      <Card style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form
          form={uploadForm}
          layout="vertical"
          initialValues={{
            province: DEFAULT_SEARCH.province,
            city: DEFAULT_SEARCH.city,
            district: DEFAULT_SEARCH.district,
            school: DEFAULT_SEARCH.school,
            grade: DEFAULT_SEARCH.grade,
            semester: DEFAULT_SEARCH.semester,
            subject: DEFAULT_SEARCH.subject,
            exam_type: DEFAULT_SEARCH.exam_type,
          }}
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))',
              gap: 16,
              alignItems: 'stretch',
            }}
          >
            <Dragger {...uploadProps} style={{ padding: 8 }}>
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">上传本地试卷文件</p>
              <p className="ant-upload-hint">支持文本型 PDF、TXT、HTML；先进入候选库，再人工解析和审核。</p>
            </Dragger>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                gap: 12,
                alignContent: 'end',
              }}
            >
              <Form.Item name="title" label="试卷标题" style={{ marginBottom: 0 }}>
                <Input placeholder="默认使用文件名" />
              </Form.Item>
              <Form.Item name="grade" label="年级" rules={[{ required: true }]} style={{ marginBottom: 0 }}>
                <Select
                  options={[
                    { value: '八年级', label: '八年级' },
                    { value: '七年级', label: '七年级' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="semester" label="册次" style={{ marginBottom: 0 }}>
                <Select
                  allowClear
                  options={[
                    { value: '上册', label: '上册' },
                    { value: '下册', label: '下册' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="subject" label="学科" rules={[{ required: true }]} style={{ marginBottom: 0 }}>
                <Select
                  options={[
                    { value: '数学', label: '数学' },
                    { value: '英语', label: '英语' },
                    { value: '语文', label: '语文' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="exam_type" label="考试类型" style={{ marginBottom: 0 }}>
                <Select
                  allowClear
                  options={[
                    { value: '期中', label: '期中' },
                    { value: '期末', label: '期末' },
                    { value: '月考', label: '月考' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="district" label="区县" style={{ marginBottom: 0 }}>
                <Input />
              </Form.Item>
              <Form.Item name="school" label="学校" style={{ marginBottom: 0 }}>
                <Input />
              </Form.Item>
              <Form.Item label=" " style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  icon={<UploadOutlined />}
                  loading={uploadSubmitting}
                  onClick={handleUploadPaperSource}
                  block
                >
                  上传并加入候选
                </Button>
              </Form.Item>
            </div>
          </div>
          <Form.Item name="province" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="city" hidden>
            <Input />
          </Form.Item>
        </Form>
      </Card>

      <Card style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form
          form={manualForm}
          layout="vertical"
          initialValues={{
            ...DEFAULT_SEARCH,
            source_adapter: 'school_official',
          }}
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: 12,
              alignItems: 'end',
            }}
          >
            <Form.Item name="title" label="试卷/页面标题" rules={[{ required: true }]} style={{ marginBottom: 0 }}>
              <Input placeholder="学校官网或试卷标题" />
            </Form.Item>
            <Form.Item
              name="source_url"
              label="来源链接"
              rules={[
                { required: true },
                { type: 'url', message: '请输入完整 URL' },
              ]}
              style={{ marginBottom: 0 }}
            >
              <Input placeholder="https://..." />
            </Form.Item>
            <Form.Item name="source_adapter" label="来源类型" style={{ marginBottom: 0 }}>
              <Select options={SOURCE_ADAPTER_OPTIONS} />
            </Form.Item>
            <Form.Item name="grade" label="年级" rules={[{ required: true }]} style={{ marginBottom: 0 }}>
              <Select
                options={[
                  { value: '八年级', label: '八年级' },
                  { value: '七年级', label: '七年级' },
                ]}
              />
            </Form.Item>
            <Form.Item name="semester" label="册次" style={{ marginBottom: 0 }}>
              <Select
                options={[
                  { value: '上册', label: '上册' },
                  { value: '下册', label: '下册' },
                ]}
              />
            </Form.Item>
            <Form.Item name="subject" label="学科" rules={[{ required: true }]} style={{ marginBottom: 0 }}>
              <Select
                options={[
                  { value: '数学', label: '数学' },
                  { value: '英语', label: '英语' },
                  { value: '语文', label: '语文' },
                ]}
              />
            </Form.Item>
            <Form.Item label=" " style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                loading={manualSubmitting}
                onClick={handleCreateManualSource}
                block
              >
                加入来源库
              </Button>
            </Form.Item>
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: 12,
              marginTop: 12,
            }}
          >
            <Form.Item name="district" label="区县" style={{ marginBottom: 0 }}>
              <Input />
            </Form.Item>
            <Form.Item name="school" label="学校" style={{ marginBottom: 0 }}>
              <Input />
            </Form.Item>
            <Form.Item name="exam_type" label="考试类型" style={{ marginBottom: 0 }}>
              <Select
                allowClear
                options={[
                  { value: '期中', label: '期中' },
                  { value: '期末', label: '期末' },
                  { value: '月考', label: '月考' },
                ]}
              />
            </Form.Item>
            <Form.Item name="snippet" label="备注/页面摘要" style={{ marginBottom: 0 }}>
              <Input placeholder="可填发现位置、页码、人工判断" />
            </Form.Item>
          </div>
          <Form.Item name="province" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="city" hidden>
            <Input />
          </Form.Item>
        </Form>
      </Card>

      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: 0 } }}>
        <div className="sb-table-toolbar">
          <div className="sb-toolbar-filters">
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索来源标题"
              value={sourceKeyword}
              onChange={(e) => setSourceKeyword(e.target.value)}
              onPressEnter={loadPapers}
              style={{ width: 240 }}
            />
            <Select
              allowClear
              placeholder="状态"
              value={statusFilter}
              onChange={setStatusFilter}
              style={{ width: 132 }}
              options={Object.entries(STATUS_META).map(([value, meta]) => ({
                value,
                label: meta.label,
              }))}
            />
            <Select
              allowClear
              placeholder="学科"
              value={subjectFilter}
              onChange={setSubjectFilter}
              style={{ width: 112 }}
              options={[
                { value: '数学', label: '数学' },
                { value: '英语', label: '英语' },
                { value: '语文', label: '语文' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={loadPapers} loading={loading}>
              刷新
            </Button>
          </div>
          <Text type="secondary" style={{ fontSize: 13 }}>
            当前显示 {papers.length} 个来源
          </Text>
        </div>
        <Table
          columns={columns}
          dataSource={papers}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1120 }}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          locale={{
            emptyText: (
              <Empty
                image={
                  <DatabaseOutlined
                    style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }}
                  />
                }
                description="还没有试卷来源，先搜索八上数学或英语试卷"
                style={{ padding: '40px 0' }}
              >
                <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                  搜索八上候选
                </Button>
              </Empty>
            ),
          }}
        />
      </Card>

      <Card style={{ borderRadius: 12, marginTop: 16 }} styles={{ body: { padding: 0 } }}>
        <div className="sb-table-toolbar">
          <div className="sb-toolbar-filters">
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索题干"
              value={itemKeyword}
              onChange={(e) => setItemKeyword(e.target.value)}
              onPressEnter={loadItems}
              style={{ width: 240 }}
            />
            <Select
              value={itemStatusFilter}
              onChange={setItemStatusFilter}
              style={{ width: 132 }}
              options={Object.entries(ITEM_STATUS_META).map(([value, meta]) => ({
                value,
                label: meta.label,
              }))}
            />
            <Button icon={<ReloadOutlined />} onClick={loadItems} loading={itemsLoading}>
              刷新题目
            </Button>
          </div>
          <Text type="secondary" style={{ fontSize: 13 }}>
            题库题目 {items.length} 道
          </Text>
        </div>
        <Table
          columns={itemColumns}
          dataSource={items}
          rowKey="id"
          loading={itemsLoading}
          size="middle"
          scroll={{ x: 980 }}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          locale={{
            emptyText: (
              <Empty
                image={<DatabaseOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />}
                description="还没有待确认题目，先对候选来源执行解析"
                style={{ padding: '36px 0' }}
              />
            ),
          }}
        />
      </Card>

      <Modal
        title={paperPreview?.title ?? '试卷预览'}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={
          <Space>
            {paperPreview?.source_url && !paperPreview.source_url.startsWith('upload://') && (
              <Button onClick={() => window.open(paperPreview.source_url, '_blank', 'noopener,noreferrer')}>
                打开来源
              </Button>
            )}
            <Button type="primary" onClick={() => setPreviewOpen(false)}>
              关闭
            </Button>
          </Space>
        }
        width={900}
      >
        {paperPreview ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type={paperPreview.status === 'available' ? 'success' : 'warning'}
              showIcon
              message={paperPreview.message}
              description={[
                `内容类型：${paperPreview.content_kind}`,
                `题量估算：${paperPreview.question_count_estimate || '未识别'}`,
                paperPreview.has_answer_signal ? '有答案信号' : '答案待确认',
              ].join(' · ')}
            />
            {paperPreview.warnings.length > 0 && (
              <Alert type="info" showIcon message={paperPreview.warnings.join('；')} />
            )}
            {paperPreview.text ? (
              <pre
                style={{
                  maxHeight: 520,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  background: 'var(--sb-color-bg-soft)',
                  border: '1px solid var(--sb-color-border-warm)',
                  borderRadius: 8,
                  padding: 16,
                  lineHeight: 1.7,
                  fontSize: 13,
                }}
              >
                {paperPreview.text}
              </pre>
            ) : (
              <Empty description="当前还没有拿到可展示的试卷正文" />
            )}
          </Space>
        ) : (
          <Empty description="暂无预览" />
        )}
      </Modal>
    </AppPageShell>
  );
}

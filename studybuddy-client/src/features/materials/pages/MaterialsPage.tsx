import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Card,
  Table,
  Button,
  Upload,
  Modal,
  Input,
  Select,
  Tag,
  Typography,
  App,
  Spin,
  Tooltip,
  Empty,
  Space,
  Alert,
} from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import StudentPageShell from '@/shared/components/StudentPageShell';
import {
  InboxOutlined,
  PlusOutlined,
  LinkOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  EyeOutlined,
  SearchOutlined,
  FileMarkdownOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { materialApi } from '@/features/materials/api';
import { useAuthStore } from '@/features/auth/store';
import { defaultMaterialName, detectMaterialType } from '@/shared/utils/material';
import { MATERIAL_TYPE_OPTIONS } from '@/shared/constants';
import type { MaterialExtraction, MaterialItem } from '@/types';
import { MarkdownContent } from '@/shared/components/MarkdownContent';

const { Text } = Typography;
const { TextArea } = Input;
const { Dragger } = Upload;

/** 待上传项：文件 + 可编辑名称/标签 + 自动类型 */
interface PendingItem {
  uid: string;
  file: File;
  name: string;
  type: string;
  knowledgeTags: string[];
}

export default function MaterialsPage() {
  const { message } = App.useApp();
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handler = () => setMobile(window.innerWidth < 768);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);
  const authVersion = useAuthStore((state) => state.authVersion);
  const [materials, setMaterials] = useState<MaterialItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  // K2: 从知识路径/深链进入时按知识点过滤
  const [searchParams] = useSearchParams();
  const tagFilter = searchParams.get('knowledge_tag') ?? null;
  // 素材在线预览状态（UX：素材预览功能）
  const [preview, setPreview] = useState<{ url: string; ext: string; name: string } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [recognizingId, setRecognizingId] = useState<number | null>(null);
  const [extractionLoading, setExtractionLoading] = useState(false);
  const [confirmingExtraction, setConfirmingExtraction] = useState(false);
  const [extraction, setExtraction] = useState<MaterialExtraction | null>(null);
  const [extractionDraft, setExtractionDraft] = useState('');

  const loadMaterials = async () => {
    setLoading(true);
    try {
      const data = await materialApi.list();
      setMaterials(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载素材列表失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPreview(null);
    setSearchText('');
    setTypeFilter(undefined);
    void loadMaterials();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authVersion]);

  const filteredMaterials = useMemo(() => {
    const keyword = searchText.trim().toLowerCase();
    return materials.filter((m) => {
      const matchKeyword =
        !keyword ||
        m.name.toLowerCase().includes(keyword) ||
        m.knowledge_tags.some((tag) => tag.toLowerCase().includes(keyword));
      const matchType = !typeFilter || m.type === typeFilter;
      // K2: knowledge_tag 深链过滤
      const matchTag = !tagFilter || m.knowledge_tags.includes(tagFilter);
      return matchKeyword && matchType && matchTag;
    });
  }, [materials, searchText, typeFilter, tagFilter]);

  // 批量选文件：去重（同 uid/同名同大小），自动判断类型、预填名称
  const uploadProps: UploadProps = {
    beforeUpload: (_file, fileList) => {
      setPending((prev) => {
        const map = new Map(prev.map((p) => [p.uid, p]));
        for (const f of fileList) {
          const uid = String(f.uid);
          if (map.has(uid)) continue;
          map.set(uid, {
            uid,
            file: f as File,
            name: defaultMaterialName(f.name),
            type: detectMaterialType(f.name),
            knowledgeTags: [],
          });
        }
        return Array.from(map.values());
      });
      return false; // 阻止自动上传，手动控制
    },
    multiple: true,
    showUploadList: false,
  };

  const removePending = (uid: string) => {
    setPending((prev) => prev.filter((p) => p.uid !== uid));
  };

  const updatePendingName = (uid: string, name: string) => {
    setPending((prev) => prev.map((p) => (p.uid === uid ? { ...p, name } : p)));
  };

  const updatePendingTags = (uid: string, knowledgeTags: string[]) => {
    setPending((prev) => prev.map((p) => (p.uid === uid ? { ...p, knowledgeTags } : p)));
  };

  const closeAndReset = () => {
    setModalOpen(false);
    setPending([]);
  };

  // 在线预览：调预览接口拿 URL + 扩展名，按扩展名选预览方式（不靠 type 字段，UX bug 修复）
  const handleDelete = (material: MaterialItem) => {
    Modal.confirm({
      title: '删除素材',
      content: `确定删除「${material.name}」吗？删除后不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await materialApi.delete(material.id);
          message.success('已删除');
          loadMaterials();
        } catch (err) {
          message.error(`删除失败：${(err as Error).message}`);
        }
      },
    });
  };

  const handlePreview = async (material: MaterialItem) => {
    setPreviewLoading(true);
    try {
      const info = await materialApi.previewUrl(material.id);
      // 优先用接口返回的 ext，回退到 name 后缀
      const ext = (info.ext || material.name.split('.').pop() || '').toLowerCase();
      if (ext === 'pdf') {
        setPreview({ url: info.url, ext: 'pdf', name: info.name });
      } else if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) {
        setPreview({ url: info.url, ext, name: info.name });
      } else {
        // 其他类型：新标签打开（下载/预览由浏览器决定）
        window.open(info.url, '_blank');
      }
    } catch {
      message.error('预览加载失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleOpenLink = async (material: MaterialItem) => {
    setPreviewLoading(true);
    try {
      const info = await materialApi.previewUrl(material.id);
      window.open(info.url, '_blank');
    } catch {
      message.error('链接打开失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleRecognize = async (material: MaterialItem) => {
    setRecognizingId(material.id);
    try {
      const result = await materialApi.recognize(material.id);
      setExtraction(result);
      setExtractionDraft(result.confirmed_markdown || result.recognized_markdown || '');
      if (result.recognition_status === 'failed' || !getExtractionContent(result).trim()) {
        message.error('没有识别到可用内容，请重新识别');
      } else if (result.auto_ready) {
        message.success('识别完成，素材已可供助手使用');
      } else {
        message.warning('识别完成，请检查可能有误的内容');
      }
      await loadMaterials();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '识别失败，请稍后重试';
      message.error(msg);
    } finally {
      setRecognizingId(null);
    }
  };

  const handleOpenExtraction = async (material: MaterialItem) => {
    setExtractionLoading(true);
    try {
      const result = await materialApi.getExtraction(material.id);
      setExtraction(result);
      setExtractionDraft(result.confirmed_markdown || result.recognized_markdown || '');
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '加载识别稿失败';
      message.error(msg);
    } finally {
      setExtractionLoading(false);
    }
  };

  const handleSaveExtraction = async () => {
    if (!extraction) return;
    if (!extractionDraft.trim()) {
      return;
    }
    setConfirmingExtraction(true);
    try {
      const result = await materialApi.confirmExtraction(extraction.material_id, extractionDraft.trim());
      setExtraction(result);
      setExtractionDraft(result.confirmed_markdown || '');
      message.success('修正内容已保存，助手会优先使用这份内容');
      await loadMaterials();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        '确认识别稿失败';
      message.error(msg);
    } finally {
      setConfirmingExtraction(false);
    }
  };

  const handleUpload = async () => {
    if (pending.length === 0) {
      message.warning('请先选择要上传的文件');
      return;
    }
    // 名称非空校验
    const empty = pending.find((p) => !p.name.trim());
    if (empty) {
      message.warning(`「${empty.file.name}」的名称不能为空`);
      return;
    }
    setUploading(true);
    let ok = 0;
    let fail = 0;
    let duplicate = 0;
    for (const item of pending) {
      try {
        const result = await materialApi.upload(item.file, item.name.trim(), item.type, item.knowledgeTags);
        if (result.is_duplicate) {
          duplicate += 1;
          message.warning(`素材已存在：${result.name}`);
          setSearchText(result.name);
        } else {
          ok += 1;
        }
      } catch {
        fail += 1;
      }
    }
    setUploading(false);
    if (fail === 0 && duplicate === 0) {
      message.success(`成功上传 ${ok} 个素材`);
    } else if (fail > 0) {
      message.warning(`上传完成：成功 ${ok} 个，失败 ${fail} 个`);
    }
    closeAndReset();
    loadMaterials();
  };

  // 待上传列表列
  const pendingColumns = [
    {
      title: '名称（可修改）',
      dataIndex: 'name',
      key: 'name',
      render: (_: unknown, record: PendingItem) => (
        <Input
          value={record.name}
          onChange={(e) => updatePendingName(record.uid, e.target.value)}
          placeholder="给素材起个名字"
          size="middle"
        />
      ),
    },
    {
      title: '知识点标签',
      dataIndex: 'knowledgeTags',
      key: 'knowledgeTags',
      width: 220,
      render: (_: unknown, record: PendingItem) => (
        <Select
          mode="tags"
          value={record.knowledgeTags}
          onChange={(tags) => updatePendingTags(record.uid, tags)}
          tokenSeparators={[',', '，', ' ']}
          placeholder="如：过去时、U5"
          maxTagCount="responsive"
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 90,
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: '文件名',
      dataIndex: 'file',
      key: 'filename',
      width: 220,
      render: (file: File) => (
        <Tooltip title={file.name}>
          <Text type="secondary" ellipsis style={{ maxWidth: 200 }} className="text-ellipsis">
            {file.name}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '大小',
      key: 'size',
      width: 80,
      render: (_: unknown, record: PendingItem) => formatSize(record.file.size),
    },
    {
      title: '',
      key: 'action',
      width: 50,
      render: (_: unknown, record: PendingItem) => (
        <Button
          type="text"
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={() => removePending(record.uid)}
        />
      ),
    },
  ];

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      className: 'sb-materials-name-col',
      onHeaderCell: () => ({ className: 'sb-materials-name-col' }),
      render: (name: string) => (
        <Tooltip title={name}>
          <Text strong className="sb-materials-name-text">{name}</Text>
        </Tooltip>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 70,
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: '知识点',
      dataIndex: 'knowledge_tags',
      key: 'knowledge_tags',
      width: 120,
      render: (tags: string[]) =>
        tags.length > 0 ? (
          <span className="sb-table-tag-stack">
            {tags.map((tag) => (
              <Tag key={tag} color="green">
                {tag}
              </Tag>
            ))}
          </span>
        ) : (
          <Text type="secondary">无</Text>
        ),
    },
    {
      title: '识别状态',
      dataIndex: 'recognition_status',
      key: 'recognition_status',
      width: 95,
      render: (_status: string, record: MaterialItem) => renderRecognitionStatus(record),
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 80,
    },
    {
      title: '上传者',
      dataIndex: 'uploaded_by',
      key: 'uploaded_by',
      width: 90,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 140,
      className: 'sb-materials-date-col',
      onHeaderCell: () => ({ className: 'sb-materials-date-col' }),
    },
    {
      title: '操作',
      key: 'action',
      width: 185,
      className: 'sb-materials-action-col',
      onHeaderCell: () => ({ className: 'sb-materials-action-col' }),
      render: (_: unknown, record: MaterialItem) => (
        <Space size={2} wrap className="sb-materials-action-list">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            loading={previewLoading && preview?.url === record.cos_url}
            onClick={() => handlePreview(record)}
          >
            预览
          </Button>
          {record.recognition_status === 'failed' ? (
            <Button
              type="link"
              size="small"
              icon={<FileMarkdownOutlined />}
              loading={extractionLoading}
              onClick={() => void handleOpenExtraction(record)}
            >
              查看识别失败详情
            </Button>
          ) : record.recognition_status === 'processing' ? (
            <Text type="secondary" className="sb-material-recognizing-copy">
              正在识别
            </Text>
          ) : record.recognition_status === 'pending' ? (
            <Text type="secondary" className="sb-material-recognizing-copy">
              待首次读取转 Markdown
            </Text>
          ) : (
            <Button
              type="link"
              size="small"
              icon={<FileMarkdownOutlined />}
              loading={extractionLoading}
              onClick={() => void handleOpenExtraction(record)}
            >
              查看识别稿
            </Button>
          )}
          <Button
            type="text"
            size="small"
            aria-label="打开素材链接"
            icon={<LinkOutlined />}
            onClick={() => void handleOpenLink(record)}
          />
          <Button
            type="text"
            danger
            size="small"
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          />
        </Space>
      ),
    },
  ];

  return (
    <StudentPageShell
      title="素材管理"
      subtitle={`共 ${materials.length} 个素材，支持按名称和知识点快速查找`}
      icon={<FolderOpenOutlined />}
      actions={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          上传素材
        </Button>
      }
    >

      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: 0 } }}>
        <div className="sb-table-toolbar">
          <div className="sb-toolbar-filters">
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索素材名或知识点"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: 240 }}
            />
            <Select
              allowClear
              placeholder="类型"
              value={typeFilter}
              onChange={setTypeFilter}
              style={{ width: 128 }}
              options={MATERIAL_TYPE_OPTIONS}
            />
          </div>
          <Text type="secondary" style={{ fontSize: 13 }}>
            当前显示 {filteredMaterials.length} 项
          </Text>
        </div>
        {loading ? (
          <PageSpinner />
        ) : mobile ? null : (
          <Table
            className="sb-materials-table"
            columns={columns}
            dataSource={filteredMaterials}
            rowKey="id"
            size="middle"
            scroll={{ x: 980 }}
            pagination={{ pageSize: 10 }}
            locale={{
              emptyText: (
                <Empty
                  image={
                    <FolderOpenOutlined
                      style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }}
                    />
                  }
                  description={
                    searchText || typeFilter
                      ? '没有匹配的素材，换个关键词或筛选条件试试'
                      : '还没有素材，上传单词表、错题照片或讲义后会显示在这里'
                  }
                  style={{ padding: '40px 0' }}
                >
                  {!searchText && !typeFilter && (
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setModalOpen(true)}
                    >
                      上传素材
                    </Button>
                  )}
                </Empty>
              ),
            }}
          />
        )}
      </Card>

      {/* 手机端素材卡片列表（Stitch screen 11） */}
      {mobile && (
      <div className="sb-material-cards">
        {loading ? (
          <PageSpinner />
        ) : filteredMaterials.length === 0 ? (
          <Empty
            image={
              <FolderOpenOutlined style={{ fontSize: 48, color: 'var(--sb-color-attr-neutral)' }} />
            }
            description="还没有素材，上传后会显示在这里"
            style={{ padding: '40px 0' }}
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              上传素材
            </Button>
          </Empty>
        ) : (
          filteredMaterials.map((m) => (
            <button
              type="button"
              key={m.id}
              className="sb-material-card"
              disabled={m.recognition_status === 'processing'}
              onClick={() => void handleOpenExtraction(m)}
              aria-label={
                m.recognition_status === 'failed'
                  ? `查看识别失败详情 ${m.name}`
                  : `查看素材 ${m.name}`
              }
            >
              <span className="sb-material-card-thumb">
                {m.type === 'image' ? (
                  <EyeOutlined />
                ) : m.type === 'pdf' ? (
                  <FileMarkdownOutlined />
                ) : (
                  <FolderOpenOutlined />
                )}
              </span>
              <span className="sb-material-card-body">
                <span className="sb-material-card-name">{m.name}</span>
                <span className="sb-material-card-meta">
                  {m.created_at} · {m.uploaded_by}
                </span>
                <span className="sb-material-card-tags">
                  {m.knowledge_tags.slice(0, 2).map((t) => (
                    <Tag key={t} className="sb-material-card-tag">{t}</Tag>
                  ))}
                  {renderRecognitionStatus(m)}
                </span>
              </span>
              <span className="sb-material-card-arrow">
                {m.recognition_status === 'processing' ? (
                  <>
                    <Spin size="small" />
                    <span>识别中</span>
                  </>
                ) : m.recognition_status === 'pending' ? (
                  <>
                    <FolderOpenOutlined />
                    <span>已上传</span>
                  </>
                ) : m.recognition_status === 'failed' ? (
                  <>
                    <ReloadOutlined />
                    <span>重试</span>
                  </>
                ) : (
                  <>
                    <EyeOutlined />
                    <span>查看</span>
                  </>
                )}
              </span>
            </button>
          ))
        )}
      </div>
      )}

      <Modal
        title="上传素材"
        open={modalOpen}
        onOk={handleUpload}
        onCancel={closeAndReset}
        confirmLoading={uploading}
        okText={pending.length ? `全部上传 (${pending.length})` : '上传'}
        cancelText="取消"
        width={720}
        destroyOnHidden
      >
        <Dragger {...uploadProps} style={{ padding: 8, marginBottom: 16 }}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到此处，支持批量选择</p>
          <p className="ant-upload-hint">类型按后缀自动识别，可逐个修改名称和标签</p>
        </Dragger>

        {pending.length > 0 && (
          <Table
            size="small"
            columns={pendingColumns}
            dataSource={pending}
            rowKey="uid"
            pagination={false}
            scroll={{ x: 790, y: 260 }}
          />
        )}
      </Modal>

      {/* 在线预览弹窗：PDF 用 iframe，图片用 img（浏览器原生，不引重库） */}
      <Modal
        title={preview?.name || '预览'}
        open={!!preview}
        onCancel={() => setPreview(null)}
        footer={null}
        width="90%"
        style={{ top: 20 }}
        styles={{ body: { padding: 0, height: 'calc(100vh - 120px)' } }}
        destroyOnHidden
      >
        {/* PDF 用 embed（iframe 在 Chromium 里不内联渲染 application/pdf，会空白） */}
        {preview?.ext === 'pdf' && (
          <embed
            src={preview.url}
            type="application/pdf"
            style={{ width: '100%', height: '100%', border: 'none' }}
          />
        )}
        {preview && ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(preview.ext) && (
          <div
            style={{
              textAlign: 'center',
              height: '100%',
              overflow: 'auto',
              background: 'var(--sb-color-bg-layout)',
            }}
          >
            <img
              src={preview.url}
              alt={preview.name}
              style={{ maxWidth: '100%', maxHeight: '100%' }}
            />
          </div>
        )}
      </Modal>

      <Modal
        title={extraction ? `${extraction.name} · Markdown 识别稿` : 'Markdown 识别稿'}
        open={!!extraction}
        onCancel={() => setExtraction(null)}
        width={860}
        destroyOnHidden
        footer={[
          <Button key="close" onClick={() => setExtraction(null)}>
            关闭
          </Button>,
          extraction?.recognition_status === 'failed' || !getExtractionContent(extraction).trim() ? (
            <Button
              key="retry"
              type="primary"
              icon={<ReloadOutlined />}
              loading={recognizingId === extraction?.material_id}
              onClick={() => {
                const item = materials.find((material) => material.id === extraction?.material_id);
                if (item) void handleRecognize(item);
              }}
            >
              重新识别
            </Button>
          ) : (
            <Button
              key="save"
              type="primary"
              icon={<CheckCircleOutlined />}
              disabled={!extractionDraft.trim()}
              loading={confirmingExtraction}
              onClick={() => void handleSaveExtraction()}
            >
              {extraction?.recognition_status === 'confirmed' ? '保存修改' : '保存修正'}
            </Button>
          ),
        ]}
      >
        {extraction?.recognition_status === 'failed' ? (
          <Alert
            type="error"
            showIcon
            message="没有识别到可用内容"
            description="可能是图片模糊、内容为空或识别服务暂时不可用。请检查原图后重新识别。"
          />
        ) : !getExtractionContent(extraction).trim() ? (
          <Alert
            type="info"
            showIcon
            message="这份素材还没有识别"
            description="点「重新识别」会把它转成 Markdown 并缓存，之后助手可以直接读取。"
          />
        ) : extraction?.recognition_status === 'confirmed' ? (
          <Alert
            type="success"
            showIcon
            message="这份素材有历史人工确认稿，助手会优先使用。"
            style={{ marginBottom: 12 }}
          />
        ) : extraction?.auto_ready ? (
          <Alert
            type="success"
            showIcon
            message="这份机器识别结果已可供助手使用。"
            style={{ marginBottom: 12 }}
          />
        ) : (
          <Alert
            type="warning"
            showIcon
            message="可供助手使用·建议核对"
            description="可直接修正不准确的内容，保存后助手会优先使用修正版。"
            style={{ marginBottom: 12 }}
          />
        )}
        {extraction?.uncertain_points?.length ? (
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary">需要确认：</Text>
            <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
              {extraction.uncertain_points.map((point) => (
                <Tag key={point} color="gold">
                  {point}
                </Tag>
              ))}
            </Space>
          </div>
        ) : null}
        {extraction && extraction.recognition_status !== 'failed' && getExtractionContent(extraction).trim() ? (
          <TextArea
            value={extractionDraft}
            onChange={(e) => setExtractionDraft(e.target.value)}
            autoSize={{ minRows: 8, maxRows: 14 }}
            placeholder="这里会显示 AI 识别出的 Markdown，可修改后保存"
            style={{ marginBottom: 14, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}
          />
        ) : null}
        {extractionDraft.trim() && (
          <div
            style={{
              border: '1px solid var(--sb-color-border)',
              borderRadius: 8,
              padding: '12px 14px',
              background: 'var(--sb-color-bg-muted)',
              maxHeight: 260,
              overflow: 'auto',
            }}
          >
            <MarkdownContent content={extractionDraft} />
          </div>
        )}
      </Modal>
    </StudentPageShell>
  );
}

/** 文件大小格式化：B/KB/MB */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function getExtractionContent(extraction: MaterialExtraction | null): string {
  return extraction?.confirmed_markdown || extraction?.recognized_markdown || '';
}

function renderRecognitionStatus(material: Pick<MaterialItem, 'recognition_status' | 'auto_ready'>) {
  const { recognition_status: status, auto_ready } = material;
  // pending=已上传待首次读取（懒识别，Agent 首次读时转 MD 并缓存）；processing=识别中（瞬时）；
  // recognized/confirmed=可供助手使用；needs_review=可用但建议核对
  if (status === 'failed') return <Tag color="red">识别失败</Tag>;
  if (status === 'processing') return <Tag color="processing">识别中</Tag>;
  if (status === 'pending') return (
    <Tooltip title="助手首次读取时会自动转成 Markdown 并缓存，之后直接读缓存">
      <Tag color="default">已上传·可用</Tag>
    </Tooltip>
  );
  if (auto_ready || status === 'confirmed') return <Tag color="green">可供助手使用</Tag>;
  return <Tag color="gold">可供助手使用·建议核对</Tag>;
}
// P2-1 agg: materials AI metadata display
// P2-1 agg: material card AI tags

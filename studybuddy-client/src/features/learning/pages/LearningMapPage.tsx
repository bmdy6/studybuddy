import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { App, Button, Empty, Skeleton, Space, Tag, Typography } from 'antd';
import {
  BookOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  NodeIndexOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import { learningMapApi } from '@/features/learning/learningMap';
import { learningFlowApi } from '@/features/learning/learningFlow';
import { useNavigate } from 'react-router-dom';
import StudentPageShell from '@/shared/components/StudentPageShell';
import { ROLES } from '@/shared/constants';
import { useAuth } from '@/features/auth/useAuth';
import type { LearningMapNode, LearningMapResource, LearningMapStatus } from '@/types';

const { Text } = Typography;

const STATUS_META: Record<LearningMapStatus, { label: string; tone: 'danger' | 'warning' | 'success' | 'default'; className: string }> = {
  weak: { label: '需要优先补', tone: 'danger', className: 'sb-learning-map-node-weak' },
  reviewing: { label: '正在巩固', tone: 'warning', className: 'sb-learning-map-node-reviewing' },
  stable: { label: '基本稳定', tone: 'success', className: 'sb-learning-map-node-stable' },
  unknown: { label: '待验证', tone: 'default', className: 'sb-learning-map-node-unknown' },
};

const RESOURCE_META: Record<LearningMapResource['type'], { label: string; icon: ReactNode }> = {
  error: { label: '错题', icon: <BookOutlined /> },
  note: { label: '笔记', icon: <FileTextOutlined /> },
  material: { label: '素材', icon: <FolderOpenOutlined /> },
  plan_item: { label: '计划', icon: <CheckCircleOutlined /> },
};

export default function LearningMapPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { role, userId, activeChildId, displayName } = useAuth();
  const studentId = role === ROLES.PARENT ? activeChildId : userId;
  const [data, setData] = useState<LearningMapNode[]>([]);
  const [summary, setSummary] = useState<Record<LearningMapStatus, number>>({
    weak: 0,
    reviewing: 0,
    stable: 0,
    unknown: 0,
  });
  const [generatedAt, setGeneratedAt] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [reviewingTag, setReviewingTag] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  // 分组折叠状态：weak/reviewing 默认展开，stable/unknown 默认收起
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({
    weak: false,
    reviewing: false,
    stable: true,
    unknown: true,
  });

  const startReview = async (tag: string) => {
    if (!studentId) return;
    setReviewingTag(tag);
    try {
      const entry = await learningFlowApi.getReviewEntry({ studentId, knowledgeTag: tag });
      const params = new URLSearchParams({ student_id: String(studentId), prompt: entry.prompt });
      navigate(`/chat?${params.toString()}`);
    } catch {
      message.error('暂时无法开始复习，请稍后重试');
    } finally {
      setReviewingTag(null);
    }
  };

  useEffect(() => {
    if (!studentId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    learningMapApi
      .get(studentId)
      .then((result) => {
        setData(result.nodes);
        setSummary({
          weak: result.summary.weak ?? 0,
          reviewing: result.summary.reviewing ?? 0,
          stable: result.summary.stable ?? 0,
          unknown: result.summary.unknown ?? 0,
        });
        setTotalCount(result.total_count ?? result.nodes.length);
        setHasMore(result.has_more ?? false);
        setGeneratedAt(result.generated_at);
        setSelectedTag(result.nodes[0]?.tag ?? null);
      })
      .catch((err: unknown) => {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '加载学习地图失败';
        message.error(msg);
      })
      .finally(() => setLoading(false));
  }, [studentId, message]);

  const selectedNode = useMemo(
    () => data.find((node) => node.tag === selectedTag) ?? data[0] ?? null,
    [data, selectedTag],
  );
  const generatedLabel = generatedAt ? generatedAt.slice(0, 16).replace('T', ' ') : '刚刚';

  if (loading) {
    return (
      <StudentPageShell title="学习地图" icon={<NodeIndexOutlined />} maxWidth={1080}>
        <Skeleton active paragraph={{ rows: 8 }} />
      </StudentPageShell>
    );
  }

  if (!studentId) {
    return (
      <StudentPageShell title="学习地图" icon={<NodeIndexOutlined />} maxWidth={1080}>
        <Empty description="请先选择一个学生" style={{ marginTop: 80 }} />
      </StudentPageShell>
    );
  }

  return (
    <StudentPageShell
      title="学习地图"
      subtitle={`${displayName ?? '学生'}的错题、笔记、素材和计划聚合视图 · 生成于 ${generatedLabel}`}
      icon={<NodeIndexOutlined />}
      metrics={[
        { label: '优先补', value: summary.weak, tone: summary.weak ? 'danger' : 'default' },
        { label: '巩固中', value: summary.reviewing, tone: 'warning' },
        { label: '基本稳定', value: summary.stable, tone: 'success' },
        { label: '待验证', value: summary.unknown },
      ]}
      maxWidth={1080}
    >
      {data.length === 0 ? (
        <section className="sb-learning-map-empty">
          <Empty
            image={<NodeIndexOutlined style={{ fontSize: 54, color: 'var(--sb-color-attr-neutral)' }} />}
            description="还没有可生成学习地图的数据"
          >
            <Text type="secondary">先上传错题、确认素材或整理笔记，地图会自动长出来。</Text>
          </Empty>
        </section>
      ) : (
        <section className="sb-learning-map-layout">
          <div className="sb-learning-map-nodes" aria-label="知识点节点">
            {/* 首屏推荐：第一个 weak 节点 */}
            {(() => {
              const nextNode = data.find((node) => node.status === 'weak') ?? data[0];
              if (!nextNode) return null;
              const meta = STATUS_META[nextNode.status];
              return (
                <div className={`sb-learning-map-next ${meta.className}`}>
                  <div className="sb-learning-map-next-body">
                    <Text type="secondary" className="sb-learning-map-kicker">
                      {nextNode.status === 'unknown' ? '待验证的知识点' : '下一个值得复习'}
                    </Text>
                    <Text strong className="sb-learning-map-next-title">
                      {nextNode.tag}
                    </Text>
                    <Text type="secondary" className="sb-learning-map-next-desc">
                      错 {nextNode.error_count} · 笔记 {nextNode.note_count} · 素材 {nextNode.material_count}
                    </Text>
                  </div>
                  <Button
                    type="primary"
                    size="small"
                    loading={reviewingTag === nextNode.tag}
                    aria-label={`开始复习${nextNode.tag}`}
                    onClick={() => startReview(nextNode.tag)}
                  >
                    开始复习
                  </Button>
                </div>
              );
            })()}

            <div className="sb-learning-map-path-head">
              <Text strong>知识路径</Text>
              <Text type="secondary">{totalCount} 个知识点{hasMore ? '，显示前 30 个' : ''}</Text>
            </div>
            <div className="sb-learning-map-path">
            {(['weak', 'reviewing', 'stable', 'unknown'] as LearningMapStatus[]).map((status) => {
              const groupNodes = data.filter((node) => node.status === status);
              const totalInGroup = summary[status] ?? 0;
              // 截断内无节点但全量有值时仍显示组头（数量来自全量 summary）
              if (totalInGroup === 0) return null;
              const meta = STATUS_META[status];
              const collapsed = collapsedGroups[status];
              return (
                <div key={status} className={`sb-learning-map-group sb-learning-map-group-${status}`}>
                  <button
                    type="button"
                    className="sb-learning-map-group-head"
                    aria-expanded={!collapsed}
                    onClick={() => setCollapsedGroups((prev) => ({ ...prev, [status]: !prev[status] }))}
                  >
                    <span className={`sb-learning-map-group-dot ${meta.className}`} />
                    <Text strong>{meta.label}</Text>
                    <Text type="secondary">
                      {totalInGroup}
                      {hasMore && groupNodes.length < totalInGroup ? `（已显示 ${groupNodes.length}）` : ''}
                    </Text>
                    <span className="sb-learning-map-group-caret">{collapsed ? '▸' : '▾'}</span>
                  </button>
                  {!collapsed && (
                    <div className="sb-learning-map-group-nodes">
                      {groupNodes.map((node, index) => {
                        const active = selectedNode?.tag === node.tag;
                        return (
                          <button
                            key={node.tag}
                            type="button"
                            className={`sb-learning-map-node ${meta.className} ${active ? 'is-active' : ''}`}
                            onClick={() => {
                              setSelectedTag(node.tag);
                              setMobileDetailOpen(true);
                            }}
                          >
                            <span className="sb-learning-map-node-index">{String(index + 1).padStart(2, '0')}</span>
                            <span className="sb-learning-map-node-main">
                              <span className="sb-learning-map-node-title">{node.tag}</span>
                              <span className="sb-learning-map-node-meta">
                                <span>错 {node.error_count}</span>
                                <span>笔记 {node.note_count}</span>
                                <span>素材 {node.material_count}</span>
                              </span>
                            </span>
                            <span className="sb-learning-map-status">{meta.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            </div>
          </div>

          <div className={`sb-learning-map-detail-wrap${mobileDetailOpen ? ' is-mobile-open' : ''}`}>
            <button
              type="button"
              className="sb-learning-map-detail-back"
              aria-label="返回知识点列表"
              onClick={() => setMobileDetailOpen(false)}
            >
              <ArrowLeftOutlined /> 知识点列表
            </button>
            <LearningMapDetail
              node={selectedNode}
              reviewing={reviewingTag === selectedNode?.tag}
              onStartReview={startReview}
            />
          </div>
        </section>
      )}
    </StudentPageShell>
  );
}

function LearningMapDetail({
  node,
  reviewing,
  onStartReview,
}: {
  node: LearningMapNode | null;
  reviewing: boolean;
  onStartReview: (tag: string) => void;
}) {
  if (!node) return null;
  const meta = STATUS_META[node.status];
  return (
    <div className="sb-learning-map-detail">
      <div className="sb-learning-map-detail-head">
        <Space direction="vertical" size={4}>
          <Text className="sb-learning-map-kicker">当前知识点</Text>
          <h2>{node.tag}</h2>
        </Space>
        <Tag className="sb-learning-map-detail-tag">{meta.label}</Tag>
      </div>

      <div className="sb-learning-map-detail-stat-grid" aria-label="当前知识点统计">
        <span>
          <Text type="secondary">错题</Text>
          <strong>{node.error_count}</strong>
        </span>
        <span>
          <Text type="secondary">笔记</Text>
          <strong>{node.note_count}</strong>
        </span>
        <span>
          <Text type="secondary">素材</Text>
          <strong>{node.material_count}</strong>
        </span>
        <span>
          <Text type="secondary">计划</Text>
          <strong>{node.plan_item_count}</strong>
        </span>
      </div>

      <div className="sb-learning-map-action-box">
        <Space align="start" direction="vertical" size={12}>
          <Button
            type="primary"
            loading={reviewing}
            aria-label={`开始复习${node.tag}`}
            onClick={() => onStartReview(node.tag)}
          >
            开始复习
          </Button>
          <Space align="start">
            <BulbOutlined className="sb-learning-map-action-icon" />
            <Space direction="vertical" size={8}>
              <Text strong>下一步建议</Text>
              <div className="sb-learning-map-action-list">
                {node.next_actions.slice(0, 1).map((action, index) => (
                  <Text key={action} className="sb-learning-map-action-text">
                    <span>{index + 1}</span>
                    {action}
                  </Text>
                ))}
              </div>
            </Space>
          </Space>
        </Space>
      </div>

      <div className="sb-learning-map-resource-head">
        <Text strong>关联记录</Text>
        <Text type="secondary">
          错题 {node.error_count} 次 · 计划 {node.plan_item_count} 项
        </Text>
      </div>

      {node.resources.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂时没有关联记录" />
      ) : (
        <div className="sb-learning-map-resource-list">
          {node.resources.map((resource) => (
            <ResourceItem key={`${resource.type}-${resource.id}`} resource={resource} tag={node.tag} />
          ))}
        </div>
      )}
    </div>
  );
}

function ResourceItem({ resource, tag }: { resource: LearningMapResource; tag: string }) {
  const meta = RESOURCE_META[resource.type];
  const navigate = useNavigate();
  const targetPath =
    resource.type === 'error' ? '/error-book' : resource.type === 'note' ? '/notes' : resource.type === 'material' ? '/materials' : null;
  return (
    <div className="sb-learning-map-resource">
      <span className="sb-learning-map-resource-icon">{meta.icon}</span>
      <span className="sb-learning-map-resource-body">
        <span className="sb-learning-map-resource-title">{resource.title}</span>
        <span className="sb-learning-map-resource-summary">{resource.summary || meta.label}</span>
      </span>
      {resource.status && <Tag>{resource.status}</Tag>}
      {resource.url && (
        <Button type="link" href={resource.url}>
          打开
        </Button>
      )}
      {targetPath && (
        <Button type="link" onClick={() => navigate(`${targetPath}?knowledge_tag=${encodeURIComponent(tag)}`)}>
          查看全部
        </Button>
      )}
    </div>
  );
}

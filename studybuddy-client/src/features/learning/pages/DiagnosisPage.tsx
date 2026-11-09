import { useEffect, useState } from 'react';
import {
  Card,
  Progress,
  Empty,
  Typography,
  Space,
  Tag,
  App,
  Button,
} from 'antd';
import { PageSpinner } from '../../../shared/components/PageSpinner';
import {
  BarChartOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { diagnosisApi } from '@/features/learning/diagnosis';
import { useAuth } from '@/features/auth/useAuth';
import StudentPageShell from '@/shared/components/StudentPageShell';
import type { DiagnosisResponse } from '@/types';

const { Text } = Typography;

export default function DiagnosisPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { userId, displayName } = useAuth();
  const [diagnosis, setDiagnosis] = useState<DiagnosisResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const data = await diagnosisApi.get(userId);
        setDiagnosis(data);
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          '加载学情诊断失败';
        message.error(msg);
      } finally {
        setLoading(false);
      }
    })();
  }, [userId, message]);

  if (loading) {
    return (
      <PageSpinner padding={120} />
    );
  }

  if (!diagnosis) {
    return (
      <StudentPageShell title="学情诊断" icon={<BarChartOutlined />} maxWidth={900}>
        <Empty description={userId ? '暂无诊断数据，多做几套试卷来看看分析' : '请先登录'} style={{ marginTop: 60 }}>
          {userId && (
            <Button type="primary" onClick={() => navigate('/exams')}>
              去做试卷
            </Button>
          )}
        </Empty>
      </StudentPageShell>
    );
  }

  const weakSorted = [...diagnosis.weak_points].sort((a, b) => b.error_rate - a.error_rate);

  const totalWrong = diagnosis.weak_points.reduce((s, w) => s + w.wrong_count, 0);
  const totalAttempts = diagnosis.weak_points.reduce((s, w) => s + w.total_attempts, 0);
  const masteredCount = diagnosis.mastered_tags.length;
  const weakCount = diagnosis.weak_points.filter((w) => !w.mastered).length;

  return (
    <StudentPageShell
      title="学情诊断"
      subtitle={`${displayName} 的学习画像 · 生成于 ${diagnosis.generated_at.slice(0, 16).replace('T', ' ')}`}
      icon={<BarChartOutlined />}
      metrics={[
        { label: '已掌握知识点', value: masteredCount, tone: 'success' },
        { label: '薄弱知识点', value: weakCount, tone: weakCount ? 'danger' : 'success' },
        { label: '累计错题', value: totalWrong, tone: totalWrong ? 'warning' : 'default' },
        { label: '累计答题', value: `${totalAttempts} 次` },
      ]}
      maxWidth={900}
    >
      {/* 薄弱知识点 */}
      <Card
        title="薄弱知识点分析"
        style={{ borderRadius: 12, marginBottom: 20 }}
        styles={{ body: { padding: 24 } }}
      >
        {weakSorted.length === 0 ? (
          <Empty description="暂无诊断数据，多做几套试卷来看看分析">
            <Button type="primary" onClick={() => navigate('/exams')}>
              去做试卷
            </Button>
          </Empty>
        ) : (
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            {weakSorted.map((wp) => (
              <div key={wp.tag}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 8,
                  }}
                >
                  <Space>
                    <Tag color={wp.mastered ? 'green' : 'orange'}>{wp.tag}</Tag>
                    {wp.mastered && (
                      <Tag color="success" icon={<CheckCircleOutlined />}>
                        已掌握
                      </Tag>
                    )}
                  </Space>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    错 {wp.wrong_count} / 共 {wp.total_attempts} 题
                  </Text>
                </div>
                <Progress
                  percent={Math.round(wp.error_rate * 100)}
                  strokeColor={
                    wp.error_rate > 0.6
                      ? 'var(--sb-color-error)'
                      : wp.error_rate > 0.3
                        ? 'var(--sb-color-warning)'
                        : 'var(--sb-color-success)'
                  }
                  format={(pct) => `错误率 ${pct}%`}
                />
              </div>
            ))}
          </Space>
        )}
      </Card>

      {/* 已掌握知识点 */}
      {diagnosis.mastered_tags.length > 0 && (
        <Card title="已掌握知识点" style={{ borderRadius: 12 }} styles={{ body: { padding: 24 } }}>
          <Space wrap>
            {diagnosis.mastered_tags.map((tag) => (
              <Tag
                key={tag}
                color="success"
                icon={<CheckCircleOutlined />}
                style={{ fontSize: 14, padding: '4px 12px', borderRadius: 6 }}
              >
                {tag}
              </Tag>
            ))}
          </Space>
        </Card>
      )}
    </StudentPageShell>
  );
}

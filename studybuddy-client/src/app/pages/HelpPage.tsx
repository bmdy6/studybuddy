import { Card, Col, Row, Space, Tabs, Tag, Timeline, Typography } from 'antd';
import type { ReactNode } from 'react';
import {
  BookOutlined,
  CalendarOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  HistoryOutlined,
  MessageOutlined,
  QuestionCircleOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import AppPageShell from '@/shared/components/AppPageShell';
import { useAuth } from '@/features/auth/useAuth';
import { ROLES } from '@/shared/constants';
import { latestReleaseNote, releaseNotes } from '@/shared/data/releaseNotes';

const { Paragraph, Text, Title } = Typography;

interface GuideStep {
  title: string;
  desc: string;
  icon: ReactNode;
}

const studentSteps: GuideStep[] = [
  {
    title: '先从对话说清楚目标',
    desc: '可以告诉助手今天想学什么、准备学多久、哪里不会。要制定计划时，先看草案，再确认创建。',
    icon: <MessageOutlined />,
  },
  {
    title: '按学习计划完成任务',
    desc: '进入学习计划页，逐项完成或跳过任务。计划不合适时，回到对话里让助手帮你调整。',
    icon: <CalendarOutlined />,
  },
  {
    title: '做完试卷再看结果',
    desc: '在我的试卷里开始答题。交卷后查看得分、解析和需要继续复习的知识点。',
    icon: <FileTextOutlined />,
  },
  {
    title: '用错题本复盘',
    desc: '错题本会沉淀反复出错的题目和知识点。复盘后可以让助手整理成笔记。',
    icon: <BookOutlined />,
  },
];

const parentSteps: GuideStep[] = [
  {
    title: '在对话里做调度',
    desc: '先说明要看学情、安排计划、讲错题还是找资源。计划类动作要让学生确认后再落库。',
    icon: <MessageOutlined />,
  },
  {
    title: '从学生页看整体状态',
    desc: '学生页聚合学情、错题、材料和近期记录，适合判断下一步该补哪一块。',
    icon: <TeamOutlined />,
  },
  {
    title: '管理试卷和素材',
    desc: '试卷管理用于查看和管理已出的试卷，素材管理用于放单词表、图片、PDF 等学习材料。',
    icon: <FolderOpenOutlined />,
  },
  {
    title: '查看更新再验收',
    desc: '每次上线后先看更新记录，确认哪些问题已修、哪些功能适合让弟弟使用。',
    icon: <HistoryOutlined />,
  },
];

function GuideCard({ step }: { step: GuideStep }) {
  return (
    <Card className="sb-help-card" variant="borderless">
      <Space align="start" size={14}>
        <span className="sb-help-card-icon">{step.icon}</span>
        <div>
          <Title level={5} style={{ margin: 0 }}>
            {step.title}
          </Title>
          <Paragraph type="secondary" style={{ margin: '8px 0 0', lineHeight: 1.7 }}>
            {step.desc}
          </Paragraph>
        </div>
      </Space>
    </Card>
  );
}

export default function HelpPage() {
  const { role } = useAuth();
  const isParent = role === ROLES.PARENT;
  const primarySteps = isParent ? parentSteps : studentSteps;
  const secondarySteps = isParent ? studentSteps : parentSteps;

  return (
    <AppPageShell
      title="帮助与更新"
      subtitle="这里放日常使用方法和上线变更记录。遇到问题时先看指南，更新后先看本页确认变化。"
      icon={<QuestionCircleOutlined />}
      metrics={[
        { label: '最新更新', value: latestReleaseNote.version, hint: latestReleaseNote.title },
        { label: '记录条数', value: releaseNotes.length, hint: '按时间倒序维护' },
        { label: '适用对象', value: isParent ? '辅导者工作台' : '学生端', hint: '自动优先展示当前角色' },
      ]}
    >
      <Tabs
        defaultActiveKey="guide"
        items={[
          {
            key: 'guide',
            label: '使用指南',
            children: (
              <Space direction="vertical" size={18} style={{ width: '100%' }}>
                <section>
                  <div className="sb-help-section-head">
                    <Title level={4}>{isParent ? '辅导者日常使用' : '学生日常使用'}</Title>
                    <Text type="secondary">优先看你当前身份最常用的流程。</Text>
                  </div>
                  <Row gutter={[14, 14]}>
                    {primarySteps.map((step) => (
                      <Col xs={24} md={12} key={step.title}>
                        <GuideCard step={step} />
                      </Col>
                    ))}
                  </Row>
                </section>

                <section>
                  <div className="sb-help-section-head">
                    <Title level={4}>{isParent ? '学生端怎么用' : '辅导者工作台怎么用'}</Title>
                    <Text type="secondary">了解另一端的页面，沟通时更容易对齐。</Text>
                  </div>
                  <Row gutter={[14, 14]}>
                    {secondarySteps.map((step) => (
                      <Col xs={24} md={12} key={step.title}>
                        <GuideCard step={step} />
                      </Col>
                    ))}
                  </Row>
                </section>
              </Space>
            ),
          },
          {
            key: 'updates',
            label: '更新记录',
            children: (
              <Card variant="borderless" className="sb-help-card">
                <Timeline
                  items={releaseNotes.map((note) => ({
                    dot: <CheckCircleOutlined style={{ color: 'var(--sb-color-primary)' }} />,
                    children: (
                      <article className="sb-release-note">
                        <Space wrap size={8}>
                          <Tag color="green">{note.version}</Tag>
                          <Tag>{note.date}</Tag>
                          <Tag>{note.audience}</Tag>
                        </Space>
                        <Title level={5} style={{ margin: '10px 0 8px' }}>
                          {note.title}
                        </Title>
                        <ul className="sb-release-list">
                          {note.items.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </article>
                    ),
                  }))}
                />
              </Card>
            ),
          },
        ]}
      />
    </AppPageShell>
  );
}

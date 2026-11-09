import { Alert, Button, Typography } from 'antd';
import {
  BarChartOutlined,
  BookOutlined,
  BulbOutlined,
  CameraOutlined,
  FileAddOutlined,
} from '@ant-design/icons';
import type { ProfileSummary } from '@/types';

const { Paragraph, Text } = Typography;

interface ParentLearningWorkbenchProps {
  studentName: string;
  profileSummary: ProfileSummary | null;
  profilePromptDismissed: boolean;
  onPrompt: (prompt: string) => void;
  onEditProfile: () => void;
  onSnoozeProfile: () => void;
}

const TASKS = [
  {
    title: '查学情',
    desc: '看薄弱知识点和最近错题',
    prompt: '分析弟弟各科薄弱点',
    icon: <BarChartOutlined />,
  },
  {
    title: '出练习',
    desc: '按知识点生成专项卷',
    prompt: '出一套英语过去式专项卷',
    icon: <FileAddOutlined />,
  },
  {
    title: '看错题',
    desc: '按知识点整理错题原因',
    prompt: '查看弟弟的错题',
    icon: <BookOutlined />,
  },
  {
    title: '推荐资源',
    desc: '找具体视频和学习材料',
    prompt: '推荐英语学习视频',
    icon: <BulbOutlined />,
  },
];

export function ParentLearningWorkbench({
  studentName,
  profileSummary,
  profilePromptDismissed,
  onPrompt,
  onEditProfile,
  onSnoozeProfile,
}: ParentLearningWorkbenchProps) {
  return (
    <div className="sb-workbench-wrap">
      <div className="sb-workbench-grid">
        <div className="sb-workbench-panel">
          <Text className="sb-kicker">当前辅导对象：{studentName}</Text>
          <Paragraph className="sb-workbench-title">今天先处理哪件学习任务？</Paragraph>
          <Text className="sb-workbench-copy">
            从学情、练习、错题和素材里选一个入口，助手会把后续步骤接起来。
          </Text>
          {profileSummary?.needs_onboarding && !profilePromptDismissed ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16, marginBottom: 16 }}
              message="学习画像待补全"
              description="直接和助手聊几句，他会问你年级、学期和学习偏好；也可去画像页手动编辑。"
              action={
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button size="small" onClick={onEditProfile}>
                    编辑画像
                  </Button>
                  <Button size="small" type="text" onClick={onSnoozeProfile}>
                    稍后
                  </Button>
                </div>
              }
            />
          ) : null}
          <div className="sb-task-grid">
            {TASKS.map((task, index) => (
              <button
                type="button"
                key={task.prompt}
                className={`sb-action-card ${index === 0 ? 'sb-action-card-primary' : ''}`}
                onClick={() => onPrompt(task.prompt)}
              >
                <div className="sb-action-card-body">
                  <span className="sb-action-icon">{task.icon}</span>
                  <div className="sb-action-text">
                    <Text className="sb-action-title" strong>
                      {task.title}
                    </Text>
                    <div className="sb-action-desc">{task.desc}</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="sb-workbench-side">
          <Text className="sb-side-title" strong>
            学习待办
          </Text>
          <div className="sb-activity-list">
            <div className="sb-activity-item">
              <BarChartOutlined style={{ color: 'var(--sb-color-primary)', marginTop: 3 }} />
              <div>
                <Text strong style={{ fontSize: 13 }}>
                  先看薄弱点
                </Text>
                <div style={{ color: 'var(--sb-color-text-secondary)', fontSize: 12 }}>
                  用诊断结果决定今天练什么
                </div>
              </div>
            </div>
            <div className="sb-activity-item">
              <BookOutlined style={{ color: 'var(--sb-color-primary)', marginTop: 3 }} />
              <div>
                <Text strong style={{ fontSize: 13 }}>
                  再处理错题
                </Text>
                <div style={{ color: 'var(--sb-color-text-secondary)', fontSize: 12 }}>
                  把重复错的知识点沉淀成笔记
                </div>
              </div>
            </div>
            <div className="sb-activity-item">
              <CameraOutlined style={{ color: 'var(--sb-color-primary)', marginTop: 3 }} />
              <div>
                <Text strong style={{ fontSize: 13 }}>
                  有照片就上传
                </Text>
                <div style={{ color: 'var(--sb-color-text-secondary)', fontSize: 12 }}>
                  左下角相机可导入错题或素材
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

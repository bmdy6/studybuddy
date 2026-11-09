import { Button, Dropdown } from 'antd';
import {
  DeleteOutlined,
  DownOutlined,
  EditOutlined,
  MessageOutlined,
  MoreOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { MenuProps } from 'antd';
import type { ChatSession } from '@/types';

interface ChatSessionControlsProps {
  sessions: ChatSession[];
  sessionId: number | null;
  onSwitch: (sessionId: number) => void;
  onCreate: () => void;
  onResetContext?: () => void;
  onRename: (sessionId: number, title: string) => void;
  onDelete: (sessionId: number) => void;
}

function buildSessionItems({
  sessions,
  sessionId,
  onRename,
  onDelete,
}: Pick<
  ChatSessionControlsProps,
  'sessions' | 'sessionId' | 'onRename' | 'onDelete'
>): NonNullable<MenuProps['items']> {
  return sessions.map((session) => ({
    key: String(session.id),
    label: (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 180 }}>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <div
            style={{
              fontWeight: session.id === sessionId ? 600 : 400,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {session.title || `会话 #${session.id}`}
          </div>
          <div style={{ fontSize: 11, color: 'var(--sb-color-text-tertiary)' }}>
            {session.created_at}
          </div>
        </div>
        <span
          onClick={(event) => {
            event.stopPropagation();
            onRename(session.id, session.title);
          }}
          style={{ cursor: 'pointer', padding: 4, color: 'var(--sb-color-text-tertiary)' }}
          title="重命名"
        >
          <EditOutlined />
        </span>
        <span
          onClick={(event) => {
            event.stopPropagation();
            onDelete(session.id);
          }}
          style={{ cursor: 'pointer', padding: 4, color: 'var(--sb-color-text-tertiary)' }}
          title="删除"
        >
          <DeleteOutlined />
        </span>
      </div>
    ),
  }));
}

export function ChatSessionToolbar(props: ChatSessionControlsProps) {
  const items = buildSessionItems(props);
  const currentSession = props.sessions.find((session) => session.id === props.sessionId);
  const currentTitle = currentSession?.title?.trim();
  const label = currentTitle && currentTitle !== '新对话' ? currentTitle : '当前对话';

  return (
    <div className="sb-chat-toolbar">
      <div className="sb-chat-toolbar-inner">
        <Dropdown
          menu={{
            items,
            onClick: ({ key }) => props.onSwitch(Number(key)),
          }}
          trigger={['click']}
          disabled={props.sessions.length === 0}
        >
          <Button type="text" icon={<MessageOutlined />} style={{ padding: '4px 8px' }}>
            <span
              style={{
                maxWidth: 180,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                display: 'inline-block',
                verticalAlign: 'middle',
              }}
            >
              {props.sessionId ? label : '正在连接'}
            </span>
            <DownOutlined style={{ fontSize: 11, marginLeft: 4 }} />
          </Button>
        </Dropdown>
        <Button
          type="text"
          icon={<PlusOutlined />}
          onClick={props.onCreate}
          className="sb-chat-new-button"
          style={{ marginLeft: 'auto', padding: '4px 8px' }}
        >
          新对话
        </Button>
      </div>
    </div>
  );
}

const RESET_CONTEXT_KEY = 'reset-context';

export function StudentConversationActions(props: ChatSessionControlsProps) {
  const sessionItems = buildSessionItems(props);
  // “开始新上下文”对主会话与 task session 都可用（用户 2026-07-26 决定去掉主会话限定）。
  const canResetContext = !!props.onResetContext;

  // “开始新上下文”放在菜单顶部（仅主会话），分隔后再列历史会话；
  // 菜单整体限高 + 内部滚动，避免手机端浮层撑满页面。点击 reset 项时 antd 会先关闭菜单，
  // 真实 resetContext 的 await import 让确认框在菜单卸载后才弹出，zIndex:1200 兜底防遮挡。
  const items: NonNullable<MenuProps['items']> = [
    ...(canResetContext
      ? [
          {
            key: RESET_CONTEXT_KEY,
            icon: <ReloadOutlined />,
            label: '开始新上下文',
            className: 'sb-conversation-reset-item',
          },
          { type: 'divider' as const },
        ]
      : []),
    ...sessionItems,
  ];

  return (
    <Dropdown
      menu={{
        items,
        onClick: ({ key }) => {
          if (key === RESET_CONTEXT_KEY) {
            props.onResetContext?.();
            return;
          }
          props.onSwitch(Number(key));
        },
      }}
      trigger={['click']}
      overlayClassName="sb-conversation-menu-overlay"
    >
      <Button
        type="text"
        shape="circle"
        icon={<MoreOutlined />}
        aria-label="对话选项"
        className="sb-conversation-menu"
      />
    </Dropdown>
  );
}

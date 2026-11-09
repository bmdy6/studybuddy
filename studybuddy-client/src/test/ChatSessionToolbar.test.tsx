import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { StudentConversationActions } from '@/features/chat/components/ChatSessionToolbar';

const mainSession = {
  id: 1,
  user_id: 1,
  student_id: 1,
  title: '学习对话',
  created_at: '',
  session_type: 'main',
  plan_id: null,
  plan_item_id: null,
  status: 'active',
};

const taskSession = {
  ...mainSession,
  id: 2,
  title: '学习任务',
  session_type: 'task',
};

function renderActions(sessionId: number) {
  const onResetContext = vi.fn();
  render(
    <StudentConversationActions
      sessions={[mainSession, taskSession]}
      sessionId={sessionId}
      onSwitch={vi.fn()}
      onCreate={vi.fn()}
      onResetContext={onResetContext}
      onRename={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: '对话选项' }));
  return onResetContext;
}

describe('StudentConversationActions', () => {
  it('主会话菜单提供开始新上下文且不再显示无效的新对话', async () => {
    const onResetContext = renderActions(1);

    const resetItem = await screen.findByRole('menuitem', { name: /开始新上下文/ });
    fireEvent.click(resetItem);

    expect(screen.queryByText('新对话')).not.toBeInTheDocument();
    expect(onResetContext).toHaveBeenCalledOnce();
  });

  it('计划会话也提供开始新上下文', async () => {
    renderActions(2);

    expect(await screen.findByText('学习对话')).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /开始新上下文/ })).toBeInTheDocument();
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ChatMessageList } from '@/features/chat/components/ChatMessageList';
import type { RenderMessage } from '@/features/chat/components/MessageBubble';

const choiceInput = {
  question: '你想重点练习数学的哪个方面？',
  options: [
    { label: '分数运算', value: 'fractions' },
    { label: '解方程', value: 'equations' },
    { label: '几何', value: 'geometry' },
  ],
};

function choiceMessage(id: string, input = choiceInput): RenderMessage {
  return {
    id,
    role: 'assistant',
    content: '你想重点练习数学的哪个方面？',
    tools: [
      {
        id: `tool-${id}`,
        name: 'present_choice_question',
        status: 'done',
        input,
      },
    ],
  };
}

describe('ChatMessageList 选择工具停用渲染', () => {
  it('choice tool 渲染成文字编号列表，多条消息各自显示', () => {
    render(
      <ChatMessageList
        messages={[choiceMessage('a'), choiceMessage('b')]}
        loading={false}
        role="student"
        sessionId={1}
        workbench={null}
      />,
    );
    expect(screen.getAllByText(/分数运算/)).toHaveLength(2);
    expect(screen.getAllByText(/解方程/)).toHaveLength(2);
    expect(screen.queryByRole('button', { name: '分数运算' })).not.toBeInTheDocument();
  });

  it('AI 正文与 choice tool 文字列表都显示', () => {
    render(
      <ChatMessageList
        messages={[choiceMessage('a')]}
        loading={false}
        role="student"
        sessionId={1}
        workbench={null}
      />,
    );
    expect(screen.getByText('你想重点练习数学的哪个方面？')).toBeInTheDocument();
    expect(screen.getByText(/1\. 分数运算/)).toBeInTheDocument();
  });
});

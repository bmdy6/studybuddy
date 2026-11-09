import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button } from 'antd';
import type { Role } from '@/shared/constants';
import {
  MessageBubble,
  type RenderMessage,
} from '@/features/chat/components/MessageBubble';

const MESSAGE_WINDOW_SIZE = 80;
const MESSAGE_WINDOW_STEP = 80;

interface ChatMessageListProps {
  messages: RenderMessage[];
  loading: boolean;
  role: Role | null;
  sessionId: number | null;
  workbench: ReactNode;
}

export function ChatMessageList({
  messages,
  loading,
  role,
  sessionId,
  workbench,
}: ChatMessageListProps) {
  const [visibleMessageCount, setVisibleMessageCount] = useState(MESSAGE_WINDOW_SIZE);
  const scrollRef = useRef<HTMLDivElement>(null);
  const visibleMessages = useMemo(() => {
    if (messages.length <= visibleMessageCount) return messages;
    return messages.slice(messages.length - visibleMessageCount);
  }, [messages, visibleMessageCount]);
  const hiddenMessageCount = Math.max(0, messages.length - visibleMessages.length);

  const showMoreMessages = useCallback(() => {
    setVisibleMessageCount((count) => Math.min(messages.length, count + MESSAGE_WINDOW_STEP));
  }, [messages.length]);

  useEffect(() => {
    setVisibleMessageCount(MESSAGE_WINDOW_SIZE);
  }, [sessionId]);

  useEffect(() => {
    if (messages.length === 0 || !scrollRef.current) return;
    const element = scrollRef.current;
    element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="sb-chat-scroll" ref={scrollRef}>
      <div className="sb-chat-inner">
        {messages.length === 0 && !loading && role === 'parent' ? workbench : null}
        {hiddenMessageCount > 0 ? (
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
            <Button
              data-testid="show-earlier-messages"
              size="small"
              onClick={showMoreMessages}
              style={{ borderRadius: 999 }}
            >
              显示更早 {Math.min(hiddenMessageCount, MESSAGE_WINDOW_STEP)} 条消息
            </Button>
          </div>
        ) : null}
        {visibleMessages.map((message) => {
          return (
            <MessageBubble
              key={message.id}
              msg={message}
            />
          );
        })}
      </div>
    </div>
  );
}

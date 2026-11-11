import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Input, Spin, Typography } from 'antd';
import { LogoutOutlined, SendOutlined } from '@ant-design/icons';
import { chat } from '../api';
import { clearToken, getToken } from '../main';

interface Msg {
  role: 'user' | 'assistant';
  content: string;
}

const { Title } = Typography;

export default function ChatPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setSending(true);
    try {
      const token = getToken();
      const result = await chat(text, token ?? '');
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: result.reply },
      ]);
    } catch (err: unknown) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '发送失败，请稍后再试。' },
      ]);
    } finally {
      setSending(false);
    }
  };

  const logout = () => {
    clearToken();
    navigate('/');
  };

  return (
    <div
      style={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--sb-color-bg-app)',
        maxWidth: 640,
        margin: '0 auto',
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          background: 'var(--sb-color-white)',
          borderBottom: '1px solid var(--sb-color-border-secondary)',
        }}
      >
        <Title level={5} style={{ margin: 0 }}>
          趣爱好
        </Title>
        <Button type="text" icon={<LogoutOutlined />} onClick={logout} aria-label="退出登录">
          退出
        </Button>
      </header>

      <main
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        {messages.length === 0 && !sending && (
          <div style={{ textAlign: 'center', marginTop: 48, color: 'var(--sb-color-text-secondary)' }}>
            <p style={{ fontSize: 16 }}>说说你想学什么，比如：</p>
            <p>「我想学唱歌」</p>
            <p>「想练英语口语，能帮我找点教程吗」</p>
            <p>「最近在练吉他，今天练了点东西」</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <div className={`sb-bubble sb-bubble--${m.role}`}>{m.content}</div>
          </div>
        ))}
        {sending && (
          <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
            <div className="sb-bubble sb-bubble--assistant">
              <Spin size="small" /> 正在想…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer
        style={{
          padding: '10px 16px calc(10px + env(safe-area-inset-bottom))',
          background: 'var(--sb-color-white)',
          borderTop: '1px solid var(--sb-color-border-secondary)',
          display: 'flex',
          gap: 8,
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={send}
          placeholder="说点什么…"
          disabled={sending}
          maxLength={2000}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={send}
          loading={sending}
          aria-label="发送"
        />
      </footer>
    </div>
  );
}

import { type ReactNode } from 'react';
import { useInRouterContext, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import './markdownMath.css';

import { repairLegacyMarkdown } from './repairLegacyMarkdown';
import { normalizeMathDelimiters } from './normalizeMathDelimiters';

/** 应用内 hash 路由链接（如 #/notes/123）：在 Router 内走 navigate 原地跳转。
 *  独立成组件，useNavigate 只在确实处于 Router 上下文时调用。 */
function InternalLink({ href, children }: { href: string; children: ReactNode }) {
  const navigate = useNavigate();
  return (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        navigate(href.slice(1));
      }}
      style={{ color: 'var(--sb-color-primary)', textDecoration: 'none', cursor: 'pointer' }}
    >
      {children}
    </a>
  );
}

/** Markdown 渲染：苹果简洁风排版，不引入第三方主题。
 *  通用组件，供 chat / note / materials 等 feature 共享使用。
 *
 *  渲染前应用保守历史修复（repairLegacyMarkdown）：覆盖 MiMo 偶发丢换行的
 *  历史消息/缓存数据；新消息（结构化终态协议渲染后）已是规范文本，修复幂等。 */
export function MarkdownContent({ content }: { content: string }) {
  const inRouter = useInRouterContext();
  return (
    <div
      className="sb-markdown"
      style={{ color: 'var(--sb-color-text)', fontSize: 14, lineHeight: 1.6 }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
        rehypePlugins={[[rehypeKatex, { trust: false, maxExpand: 1000 }]]}
        components={{
          h1: ({ children }) => (
            <h3 style={{ fontSize: 18, margin: '16px 0 8px', fontWeight: 600 }}>{children}</h3>
          ),
          h2: ({ children }) => (
            <h3 style={{ fontSize: 16, margin: '14px 0 6px', fontWeight: 600 }}>{children}</h3>
          ),
          h3: ({ children }) => (
            <h4 style={{ fontSize: 15, margin: '12px 0 4px', fontWeight: 600 }}>{children}</h4>
          ),
          h4: ({ children }) => (
            <h5 style={{ fontSize: 14, margin: '10px 0 4px', fontWeight: 600 }}>{children}</h5>
          ),
          p: ({ children }) => <p style={{ margin: '4px 0' }}>{children}</p>,
          ul: ({ children }) => <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul>,
          ol: ({ children }) => <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol>,
          li: ({ children }) => <li style={{ margin: '2px 0' }}>{children}</li>,
          strong: ({ children }) => (
            <strong style={{ fontWeight: 600, color: 'var(--sb-color-text)' }}>{children}</strong>
          ),
          code: ({ className, children }) => {
            const isBlock = /language-/.test(className || '');
            if (isBlock) {
              return (
                <pre
                  style={{
                    background: 'var(--sb-color-bg-muted)',
                    borderRadius: 8,
                    padding: '12px 14px',
                    overflowX: 'auto',
                    fontSize: 13,
                    margin: '4px 0',
                  }}
                >
                  <code>{children}</code>
                </pre>
              );
            }
            return (
              <code
                style={{
                  background: 'var(--sb-color-bg-muted)',
                  padding: '2px 5px',
                  borderRadius: 4,
                  fontSize: 13,
                }}
              >
                {children}
              </code>
            );
          },
          a: ({ children, href }) => {
            // 应用内 hash 路由（如 #/notes/123）在 Router 内走原地 navigate，不新开标签页；
            // 不在 Router 上下文时降级成普通 hash 锚点（浏览器原生跳转）
            if (href && href.startsWith('#/')) {
              if (inRouter) {
                return <InternalLink href={href}>{children}</InternalLink>;
              }
              return (
                <a
                  href={href}
                  style={{ color: 'var(--sb-color-primary)', textDecoration: 'none' }}
                >
                  {children}
                </a>
              );
            }
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: 'var(--sb-color-primary)', textDecoration: 'none' }}
              >
                {children}
              </a>
            );
          },
          blockquote: ({ children }) => (
            <blockquote
              style={{
                borderLeft: '3px solid var(--sb-color-border-blockquote)',
                margin: '8px 0',
                paddingLeft: 12,
                color: 'var(--sb-color-text-soft)',
              }}
            >
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div style={{ overflowX: 'auto', margin: '8px 0' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th
              style={{
                border: '1px solid var(--sb-color-border-secondary)',
                padding: '6px 10px',
                background: 'var(--sb-color-bg-muted)',
                fontWeight: 600,
                textAlign: 'left',
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td
              style={{ border: '1px solid var(--sb-color-border-secondary)', padding: '6px 10px' }}
            >
              {children}
            </td>
          ),
        }}
      >
        {repairLegacyMarkdown(normalizeMathDelimiters(content))}
      </ReactMarkdown>
    </div>
  );
}
// agg-1 P2

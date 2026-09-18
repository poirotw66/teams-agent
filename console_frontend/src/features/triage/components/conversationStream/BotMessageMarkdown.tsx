import React from 'react';
import { Tag } from 'antd';
import { ExportOutlined, FileTextOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CitationItem } from '../../../../shared/api/types';
import { enrichMessageMarkdown } from './enrichMessageMarkdown';

interface BotMessageMarkdownProps {
  content: string;
  citations?: CitationItem[];
  onSelectCitation: (identifier: string, citations?: CitationItem[]) => void;
}

export const BotMessageMarkdown: React.FC<BotMessageMarkdownProps> = ({
  content,
  citations,
  onSelectCitation,
}) => (
  <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    skipHtml
    components={{
      p: ({ children }) => (
        <p style={{ margin: '0 0 8px 0', lineHeight: 1.6, fontSize: '14px', color: '#242424' }}>
          {children}
        </p>
      ),
      h1: ({ children }) => (
        <h4 style={{ margin: '12px 0 8px', fontSize: '15px', fontWeight: 600, color: '#1B1B1F' }}>
          {children}
        </h4>
      ),
      h2: ({ children }) => (
        <h5 style={{ margin: '10px 0 6px', fontSize: '14.5px', fontWeight: 600, color: '#1B1B1F' }}>
          {children}
        </h5>
      ),
      h3: ({ children }) => (
        <h6 style={{ margin: '8px 0 4px', fontSize: '14px', fontWeight: 600, color: '#1B1B1F' }}>
          {children}
        </h6>
      ),
      hr: () => (
        <hr style={{ border: 'none', borderTop: '1px solid #E1DFDD', margin: '12px 0' }} />
      ),
      ul: ({ children }) => (
        <ul style={{ margin: '0 0 8px 0', paddingLeft: '22px', lineHeight: 1.6 }}>{children}</ul>
      ),
      ol: ({ children }) => (
        <ol style={{ margin: '0 0 8px 0', paddingLeft: '22px', lineHeight: 1.6 }}>{children}</ol>
      ),
      li: ({ children }) => (
        <li style={{ marginBottom: '4px', fontSize: '14px', color: '#242424' }}>{children}</li>
      ),
      blockquote: ({ children }) => (
        <blockquote
          style={{
            margin: '10px 0',
            padding: '8px 14px',
            borderLeft: '4px solid #5B5FC7',
            backgroundColor: '#F5F6FC',
            borderRadius: '0 6px 6px 0',
            color: '#323130',
            fontSize: '13.5px',
            lineHeight: 1.55,
          }}
        >
          {children}
        </blockquote>
      ),
      strong: ({ children }) => (
        <strong style={{ fontWeight: 600, color: '#1B1B1F' }}>{children}</strong>
      ),
      code: ({ children }) => (
        <code
          style={{
            backgroundColor: '#EBEBF2',
            padding: '2px 5px',
            borderRadius: '4px',
            fontSize: '12.5px',
            fontFamily: 'Consolas, monospace',
            color: '#5B5FC7',
          }}
        >
          {children}
        </code>
      ),
      a: ({ href, children }) => {
        if (href?.startsWith('#citation-')) {
          const identifier = href.replace('#citation-', '');
          const isPolicy = identifier.startsWith('POLICY-SEC');
          const textStr = String(children);
          const isBadgePill = textStr === identifier || textStr === `[${identifier}]`;

          if (isBadgePill) {
            return (
              <Tag
                color={isPolicy ? 'volcano' : 'purple'}
                style={{
                  cursor: 'pointer',
                  margin: '0 3px',
                  fontSize: '11px',
                  fontWeight: 600,
                  borderRadius: '10px',
                  lineHeight: '19px',
                  padding: '0 7px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  verticalAlign: 'baseline',
                  transform: 'translateY(-1px)',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
                  transition: 'all 0.2s',
                }}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onSelectCitation(identifier, citations);
                }}
                title={`點擊查看引用依據：${identifier}`}
              >
                {isPolicy ? '🛡️ ' : '📄 '}
                {children}
              </Tag>
            );
          }

          return (
            <a
              href={`#${identifier}`}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onSelectCitation(identifier, citations);
              }}
              style={{
                color: '#5B5FC7',
                fontWeight: 500,
                textDecoration: 'underline',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '3px',
              }}
            >
              {children}
              <FileTextOutlined style={{ fontSize: '12px' }} />
            </a>
          );
        }

        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: '#5B5FC7',
              textDecoration: 'underline',
              fontWeight: 500,
              wordBreak: 'break-word',
            }}
          >
            {children}
            <ExportOutlined style={{ fontSize: '11px', marginLeft: '3px' }} />
          </a>
        );
      },
    }}
  >
    {enrichMessageMarkdown(content)}
  </ReactMarkdown>
);

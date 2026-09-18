import React, { useState } from 'react';
import {
  Card,
  Space,
  Typography,
  Tag,
  Avatar,
  Alert,
  Collapse,
  Button,
  Drawer,
  Spin,
  Tooltip,
  message,
} from 'antd';
import {
  UserOutlined,
  RobotOutlined,
  DislikeOutlined,
  FileTextOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  DownloadOutlined,
  ExportOutlined,
  EyeOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ConversationDetail, CitationItem } from '../../../shared/api/types';
import { apiClient } from '../../../shared/api/client';

const { Text } = Typography;

interface ConversationStreamProps {
  conversation: ConversationDetail | null;
}

const GLOBAL_SECURITY_POLICIES: Record<
  string,
  { title: string; summary: string; body: string }
> = {
  'POLICY-SEC-001': {
    title: '全域資料最小化原則',
    summary: '提交畫面或附件前須避免與問題無關的個人及敏感資訊。',
    body: '全域資料最小化原則：使用者提供畫面截圖或附件時，嚴禁提交與問題或異常無關的個人及敏感資訊。若畫面包含無關的個人或敏感資訊，不應直接提交，應提醒使用者先行確認處理方式，不得宣稱或推論「無須遵守資料最小化」。',
  },
  'POLICY-SEC-002': {
    title: '絕對機敏資訊禁令',
    summary: '登入密碼、憑證密碼與動態驗證碼嚴禁於任何回報中提供。',
    body: '絕對機敏資訊禁令：登入密碼、個人憑證密碼、動態驗證碼等機敏資訊，在任何問題回報或諮詢中皆嚴禁於信件、畫面或文字中提供。',
  },
  'POLICY-SEC-003': {
    title: '安全性設定變更確認原則',
    summary: '變更 Proxy、憑證或安全性設定前須向權責單位確認。',
    body: '安全性設定變更確認原則：涉及停用安全性設定（如關閉 Proxy、變更安全性區域或憑證設定）時，若裝置是否受企業管控政策管理尚未確認，必須先向權責單位或資訊部門確認適用性，切勿擅自變更。',
  },
};

/** Preprocess bot text to enrich citation markers, normalize headings, unpack steps, and preserve line breaks */
export function enrichMessageMarkdown(content: string): string {
  if (!content) return '';

  let enriched = content.trim();

  // 1. Normalize "問題：" header
  enriched = enriched.replace(
    /(?:^|\n)(?:\*\*)?問題：(?:\*\*)?\s*([^\n]+)/g,
    '\n\n**問題：** $1\n\n'
  );

  // 2. Normalize "處理方式：" header to ensure double newline separation
  enriched = enriched.replace(
    /(?:\n\s*|\A)(?:\*\*)?處理方式：(?:\*\*)?\s*/g,
    '\n\n**處理方式：**\n\n'
  );

  // 3. Normalize "注意事項" / "備註" / "註" callout blockquotes
  enriched = enriched.replace(
    /(?:^|\n)(?:>\s*)?(?:💡\s*)?(?:\*\*)?(?:注意事項|註|備註)[：:]?(?:\*\*)?[ \t]*\n*([\s\S]*?)(?=(?:\n\s*(?:\*\*|來源|問題|處理方式)|\n\n\n|$))/g,
    (_m, body) => {
      const lines = body.trim().split('\n').map((l: string) => l.trim()).filter(Boolean);
      if (lines.length === 0) return '\n\n> 💡 **注意事項**：\n\n';
      if (lines.length === 1) {
        return `\n\n> 💡 **注意事項**：${lines[0].replace(/^[-*]\s*/, '')}\n\n`;
      }
      const quotedLines = lines
        .map((l: string) => `> ${l.startsWith('- ') || l.startsWith('* ') ? l : `- ${l}`}`)
        .join('\n');
      return `\n\n> 💡 **注意事項**：\n>\n${quotedLines}\n\n`;
    }
  );

  // 4. Normalize "來源：" or "來源" header
  enriched = enriched.replace(
    /(?:\n\s*|\A)(?:\*\*)?來源[：:]?(?:\*\*)?\s*(?=\n|$)/g,
    '\n\n**來源**\n\n'
  );

  // 5. Unpack inline numbered steps into true ordered lists
  // 5a. Lead-in sentence into Step 1
  enriched = enriched.replace(
    /(?<!\n)(?:([：:。；;!?！？])\s*|\s+)1\.\s+/g,
    (_m, p1) => (p1 ? `${p1}\n\n1. ` : '\n\n1. ')
  );
  // 5b. Subsequent steps (2., 3., etc.)
  enriched = enriched.replace(
    /(?<!\n)(?:([：:。；;!?！？])\s*|\s+)(\d+)\.\s+/g,
    (_m, p1, p2) => (p1 ? `${p1}\n${p2}. ` : `\n${p2}. `)
  );
  // 5c. Ensure blank line before step 1 if preceded by non-empty line
  enriched = enriched.replace(/([^\n])\n1\.\s+/g, '$1\n\n1. ');

  // 6. Transform source lines like "[S1] Document Title" or "- [S1] Document Title"
  enriched = enriched.replace(
    /(?:^|\n)\s*(?:-\s*)?\[(S\d+|POLICY-SEC-\d{3})\]\s+([^\n\[(]+(?:\([^)]*\)[^\n\[(]*)?)(?=$|\n)/g,
    (_match, tag, title) => {
      const cleanTitle = title.trim();
      return `\n- [${tag}](#citation-${tag}) [${cleanTitle}](#citation-${tag})`;
    }
  );

  // 7. Transform remaining inline markers like [S1] or [POLICY-SEC-001]
  enriched = enriched.replace(
    /(?<!\[)\[(S\d+|POLICY-SEC-\d{3})\](?!\()/g,
    '[$1](#citation-$1)'
  );

  // 8. Convert single newlines in plain paragraphs to hard breaks (2 trailing spaces)
  // so CommonMark preserves intended line breaks instead of collapsing them
  const lines = enriched.split('\n');
  const processedLines = lines.map((line, idx) => {
    if (!line.trim()) return line;
    // Keep list items, blockquotes, tables, and headers as markdown blocks
    if (/^\s*(?:[-*+]|\d+\.|#|>|\|)/.test(line)) return line;
    const nextLine = lines[idx + 1];
    if (
      nextLine === undefined ||
      !nextLine.trim() ||
      /^\s*(?:[-*+]|\d+\.|#|>|\|)/.test(nextLine)
    ) {
      return line;
    }
    return line.endsWith('  ') ? line : `${line}  `;
  });

  return processedLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

export const ConversationStream: React.FC<ConversationStreamProps> = ({
  conversation,
}) => {
  const [selectedCitation, setSelectedCitation] = useState<CitationItem | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [loadingPreview, setLoadingPreview] = useState<boolean>(false);

  if (!conversation) {
    return (
      <Card
        style={{
          borderRadius: 8,
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text type="secondary">請從左側佇列中選擇一筆對話進行檢視與分診</Text>
      </Card>
    );
  }

  const handleSelectCitation = async (
    identifier: string,
    citations?: CitationItem[]
  ) => {
    const list = citations || [];
    let target: CitationItem | undefined;

    // Match by rank S1, S2, etc.
    const sMatch = identifier.match(/^S(\d+)$/i);
    if (sMatch) {
      const idx = parseInt(sMatch[1], 10) - 1;
      if (list[idx]) {
        target = list[idx];
      }
    }

    // Match by document_id or chunk_id or policy_id
    if (!target) {
      target = list.find(
        (c) =>
          c.document_id === identifier ||
          c.chunk_id === identifier ||
          c.policy_id === identifier ||
          (c.document_title && c.document_title.includes(identifier))
      );
    }

    // Fallback for security policy
    if (!target && identifier.startsWith('POLICY-SEC-')) {
      const pol = GLOBAL_SECURITY_POLICIES[identifier];
      if (pol) {
        target = {
          document_id: identifier,
          document_title: `${pol.title} (${identifier})`,
          similarity_score: 100,
          snippet: pol.summary,
          content: pol.body,
          updated_at: '2026-09-10',
          source_type: 'POLICY_ADVISORY',
          is_policy: true,
          policy_id: identifier,
        };
      }
    }

    if (!target) {
      target = {
        document_id: identifier,
        document_title: `引用資料來源 (${identifier})`,
        similarity_score: 90,
        snippet: '此項目為對話標註之引用依據。',
        updated_at: '2026-09-10',
        source_type: 'DOCUMENT',
      };
    }

    setSelectedCitation(target);
    setDrawerOpen(true);

    // If source_ref_id is present and content is not cached, fetch from backend
    if (target.source_ref_id && !target.content) {
      setLoadingPreview(true);
      try {
        const preview = await apiClient<{
          content?: string;
          downloadUrl?: string;
          sourcePath?: string;
        }>(`/api/sources/${target.source_ref_id}`);
        if (preview) {
          setSelectedCitation((prev) =>
            prev
              ? {
                  ...prev,
                  content: preview.content || prev.content,
                  download_url: preview.downloadUrl || prev.download_url,
                  source_path: preview.sourcePath || prev.source_path,
                }
              : null
          );
        }
      } catch (err) {
        console.debug('Failed to fetch source preview:', err);
      } finally {
        setLoadingPreview(false);
      }
    }
  };

  const handleCopyPath = (path: string) => {
    navigator.clipboard.writeText(path);
    message.success('路徑已複製至剪貼簿');
  };

  return (
    <>
      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <Space size="middle">
                <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#5B5FC7' }} />
                <div>
                  <Text strong style={{ fontSize: '15px' }}>
                    {conversation.reporter_dept} - {conversation.reporter_name}
                  </Text>
                  <Text type="secondary" style={{ fontSize: '12px', marginLeft: 8 }}>
                    分機：{conversation.reporter_ext || '未提供'} | 開始時間：{conversation.started_at}
                  </Text>
                </div>
              </Space>
            </div>
            <Space>
              {conversation.status === 'RESOLVED' && (
                <Tag style={{ backgroundColor: '#EBF6EC', color: '#107C41', borderColor: '#BDE3C4' }}>已結案</Tag>
              )}
              {conversation.status === 'ESCALATED_TICKET' && (
                <Tag style={{ backgroundColor: '#F0F1FA', color: '#5B5FC7', borderColor: '#D1D3E0' }}>
                  已轉立工單 [{conversation.associated_ticket_id}]
                </Tag>
              )}
              {conversation.status === 'PENDING_REVIEW' && (
                <Tag style={{ backgroundColor: '#FFF8E6', color: '#B78800', borderColor: '#F5D38A' }}>待排查</Tag>
              )}
            </Space>
          </div>
        }
        style={{ borderRadius: 8, height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{
          body: {
            padding: '16px',
            flex: 1,
            overflowY: 'auto',
            maxHeight: '720px',
            backgroundColor: '#f8f9fa',
          },
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {conversation.messages.map((msg) => {
            if (msg.sender === 'system') {
              return (
                <div key={msg.id} style={{ textAlign: 'center', margin: '8px 0' }}>
                  <Tag color="geekblue" icon={<CheckCircleOutlined />}>
                    {msg.content} · {msg.timestamp}
                  </Tag>
                </div>
              );
            }

            const isUser = msg.sender === 'user';

            return (
              <div
                key={msg.id}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isUser ? 'flex-end' : 'flex-start',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '8px',
                    maxWidth: '88%',
                    flexDirection: isUser ? 'row-reverse' : 'row',
                  }}
                >
                  <Avatar
                    icon={isUser ? <UserOutlined /> : <RobotOutlined />}
                    style={{
                      backgroundColor: isUser ? '#5b5fc7' : '#4f52b2',
                      flexShrink: 0,
                      marginTop: 4,
                    }}
                  />

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      className={isUser ? 'teams-bubble-user' : 'teams-bubble-bot'}
                      style={{
                        padding: '12px 16px',
                        fontSize: '14px',
                        lineHeight: 1.6,
                        overflowWrap: 'anywhere',
                      }}
                    >
                      {isUser ? (
                        <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                      ) : (
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
                                        handleSelectCitation(identifier, msg.citations);
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
                                      handleSelectCitation(identifier, msg.citations);
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
                          {enrichMessageMarkdown(msg.content)}
                        </ReactMarkdown>
                      )}
                    </div>

                    {/* Feedback badges */}
                    {msg.feedback === 'negative' && (
                      <div style={{ marginTop: 6, textAlign: 'left' }}>
                        <Alert
                          type="error"
                          showIcon
                          icon={<DislikeOutlined style={{ color: '#c4314b' }} />}
                          message={
                            <Text style={{ fontSize: '12px', color: '#c4314b', fontWeight: 500 }}>
                              同仁回饋：👎 未解決 {msg.feedback_comment ? `（原因：${msg.feedback_comment}）` : '（未留備註）'}
                            </Text>
                          }
                          style={{
                            padding: '4px 10px',
                            borderRadius: 6,
                            display: 'inline-block',
                            backgroundColor: '#fdf3f4',
                            borderColor: '#f6ccd2',
                          }}
                        />
                      </div>
                    )}

                    {msg.feedback === 'positive' && (
                      <div style={{ marginTop: 6, textAlign: 'left' }}>
                        <Tag
                          icon={<CheckCircleOutlined style={{ color: '#107C41' }} />}
                          style={{
                            backgroundColor: '#EBF6EC',
                            color: '#107C41',
                            borderColor: '#BDE3C4',
                            padding: '2px 8px',
                            borderRadius: 6,
                            fontSize: '12px',
                          }}
                        >
                          同仁回饋：👍 已解決問題
                        </Tag>
                      </div>
                    )}

                    {/* Citations details accordion under bot responses */}
                    {!isUser && msg.citations && msg.citations.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <Collapse
                          size="small"
                          ghost
                          defaultActiveKey={['citations']}
                          items={[
                            {
                              key: 'citations',
                              label: (
                                <Space size="small">
                                  <FileTextOutlined style={{ color: '#5B5FC7' }} />
                                  <Text strong style={{ fontSize: '12px', color: '#5B5FC7' }}>
                                    當時 AI 檢索與引用依據 ({msg.citations.length} 份依據)
                                  </Text>
                                </Space>
                              ),
                              children: (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                  {msg.citations.map((cite, idx) => {
                                    const isPolicy =
                                      cite.is_policy ||
                                      cite.source_type === 'POLICY_ADVISORY' ||
                                      (cite.chunk_id && cite.chunk_id.startsWith('POLICY-SEC'));

                                    return (
                                      <div
                                        key={idx}
                                        className="teams-card-hover"
                                        onClick={() => {
                                          setSelectedCitation(cite);
                                          setDrawerOpen(true);
                                        }}
                                        style={{
                                          padding: '10px 14px',
                                          backgroundColor: '#ffffff',
                                          border: '1px solid #E1DFDD',
                                          borderRadius: 8,
                                          cursor: 'pointer',
                                          transition: 'all 0.2s cubic-bezier(0.32, 0.72, 0, 1)',
                                        }}
                                      >
                                        <div
                                          style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                            marginBottom: 4,
                                          }}
                                        >
                                          <Space size="small">
                                            <Tag
                                              color={isPolicy ? 'volcano' : 'purple'}
                                              style={{ fontWeight: 600, borderRadius: 4 }}
                                            >
                                              {isPolicy ? '🛡️ [政策]' : `[S${idx + 1}]`}
                                            </Tag>
                                            <Text strong style={{ fontSize: '13px', color: '#242424' }}>
                                              {cite.document_title}
                                            </Text>
                                            {isPolicy ? (
                                              <Tag color="volcano">資安政策規範</Tag>
                                            ) : cite.source_type === 'FAQ' ? (
                                              <Tag color="green">FAQ 知識庫</Tag>
                                            ) : (
                                              <Tag color="blue">文件依據</Tag>
                                            )}
                                          </Space>
                                          <Space>
                                            {isPolicy ? (
                                              <Tag color="purple">全域強制規範</Tag>
                                            ) : (
                                              <Tag color="cyan">相似度 {cite.similarity_score}%</Tag>
                                            )}
                                            {cite.is_stale && (
                                              <Tag color="warning" icon={<WarningOutlined />}>
                                                ⚠️ 超過 1 年未更新
                                              </Tag>
                                            )}
                                          </Space>
                                        </div>

                                        <div style={{ margin: '6px 0', color: '#605E5C', fontSize: '12px', lineHeight: 1.5 }}>
                                          引用依據：{cite.snippet}
                                        </div>

                                        <div
                                          style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                            marginTop: 6,
                                            paddingTop: 6,
                                            borderTop: '1px solid #F3F2F1',
                                          }}
                                        >
                                          <Text type="secondary" style={{ fontSize: '11px' }}>
                                            {cite.source_path ? `路徑: ${cite.source_path}` : `最後維護時間：${cite.updated_at}`}
                                          </Text>
                                          <Space size="small">
                                            <Button
                                              type="link"
                                              size="small"
                                              icon={<EyeOutlined />}
                                              style={{ color: '#5B5FC7', padding: 0, height: 'auto', fontSize: '12px' }}
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                setSelectedCitation(cite);
                                                setDrawerOpen(true);
                                              }}
                                            >
                                              檢視引用內容
                                            </Button>
                                            {cite.download_url && (
                                              <Button
                                                type="link"
                                                size="small"
                                                icon={<DownloadOutlined />}
                                                style={{ color: '#107C41', padding: 0, height: 'auto', fontSize: '12px' }}
                                                onClick={(e) => {
                                                  e.stopPropagation();
                                                  window.open(cite.download_url, '_blank');
                                                }}
                                              >
                                                下載原檔
                                              </Button>
                                            )}
                                            {cite.url && (
                                              <Button
                                                type="link"
                                                size="small"
                                                icon={<ExportOutlined />}
                                                style={{ color: '#5B5FC7', padding: 0, height: 'auto', fontSize: '12px' }}
                                                onClick={(e) => {
                                                  e.stopPropagation();
                                                  window.open(cite.url, '_blank');
                                                }}
                                              >
                                                前往原文
                                              </Button>
                                            )}
                                          </Space>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              ),
                            },
                          ]}
                        />
                      </div>
                    )}

                    <div
                      style={{
                        fontSize: '11px',
                        color: '#8c8c8c',
                        marginTop: 4,
                        textAlign: isUser ? 'right' : 'left',
                      }}
                    >
                      {msg.timestamp}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Citation Detail & Preview Drawer */}
      <Drawer
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setSelectedCitation(null);
        }}
        width={560}
        title={
          selectedCitation ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {selectedCitation.is_policy || selectedCitation.source_type === 'POLICY_ADVISORY' ? (
                <SafetyCertificateOutlined style={{ color: '#D83B01', fontSize: '20px' }} />
              ) : (
                <FileTextOutlined style={{ color: '#5B5FC7', fontSize: '20px' }} />
              )}
              <div>
                <div style={{ fontSize: '15px', fontWeight: 600, color: '#242424' }}>
                  {selectedCitation.document_title}
                </div>
                <div style={{ fontSize: '11px', color: '#605E5C', fontWeight: 'normal' }}>
                  文件編號：{selectedCitation.document_id}
                  {selectedCitation.chunk_id ? ` · 段落：${selectedCitation.chunk_id}` : ''}
                </div>
              </div>
            </div>
          ) : (
            '引用來源依據詳情'
          )
        }
        extra={
          <Space>
            {selectedCitation?.download_url && (
              <Button
                type="primary"
                size="small"
                icon={<DownloadOutlined />}
                style={{ backgroundColor: '#107C41' }}
                onClick={() => window.open(selectedCitation.download_url, '_blank')}
              >
                下載原檔
              </Button>
            )}
            {selectedCitation?.url && (
              <Button
                size="small"
                icon={<ExportOutlined />}
                onClick={() => window.open(selectedCitation.url, '_blank')}
              >
                開啟連結
              </Button>
            )}
          </Space>
        }
      >
        {selectedCitation && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Status Tags */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {selectedCitation.is_policy || selectedCitation.source_type === 'POLICY_ADVISORY' ? (
                <Tag color="volcano" icon={<SafetyCertificateOutlined />}>
                  資安政策規範
                </Tag>
              ) : selectedCitation.source_type === 'FAQ' ? (
                <Tag color="green">FAQ 知識庫</Tag>
              ) : (
                <Tag color="blue">文件依據</Tag>
              )}

              {selectedCitation.is_policy || selectedCitation.source_type === 'POLICY_ADVISORY' ? (
                <Tag color="purple">全域強制約束</Tag>
              ) : (
                <Tag color="cyan">相似度 {selectedCitation.similarity_score}%</Tag>
              )}

              {selectedCitation.is_stale && (
                <Tag color="warning" icon={<WarningOutlined />}>
                  ⚠️ 超過 1 年未更新
                </Tag>
              )}
            </div>

            {/* Source Path */}
            {selectedCitation.source_path && (
              <Card size="small" style={{ backgroundColor: '#F8F9FA' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text type="secondary" style={{ fontSize: '12px' }}>
                    來源路徑：
                    <code style={{ marginLeft: 6, color: '#242424', fontSize: '12px' }}>
                      {selectedCitation.source_path}
                    </code>
                  </Text>
                  <Tooltip title="複製路徑">
                    <Button
                      type="text"
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={() => handleCopyPath(selectedCitation.source_path!)}
                    />
                  </Tooltip>
                </div>
              </Card>
            )}

            {/* Stale Warning Banner */}
            {selectedCitation.is_stale && (
              <Alert
                type="warning"
                showIcon
                message="版本維護提醒"
                description="此文件已超過 1 年未更新，內容可能與現行作業規範有出入，建議資訊維運人員進行內容校閱或更新知識庫。"
              />
            )}

            {/* Loading Spinner */}
            {loadingPreview ? (
              <div style={{ textAlign: 'center', padding: '40px 0' }}>
                <Spin tip="正在獲取版本依據與原檔內容..." />
              </div>
            ) : selectedCitation.is_policy || selectedCitation.source_type === 'POLICY_ADVISORY' ? (
              /* Security Policy Display */
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Card
                  title={<Text strong style={{ fontSize: '13px', color: '#D83B01' }}>🛡️ 政策摘要</Text>}
                  size="small"
                  style={{ backgroundColor: '#FFF9F5', borderColor: '#FED9CC' }}
                >
                  <Text style={{ fontSize: '13px', color: '#424242' }}>
                    {selectedCitation.snippet}
                  </Text>
                </Card>

                <Card
                  title={<Text strong style={{ fontSize: '13px' }}>法規／安全規範全文</Text>}
                  size="small"
                >
                  <div
                    style={{
                      padding: '12px 14px',
                      backgroundColor: '#FAFAFA',
                      borderLeft: '4px solid #D83B01',
                      borderRadius: '0 6px 6px 0',
                      fontSize: '13.5px',
                      lineHeight: 1.6,
                      color: '#242424',
                    }}
                  >
                    {selectedCitation.content || selectedCitation.snippet}
                  </div>
                </Card>

                <Alert
                  type="info"
                  showIcon
                  message="合規遵循說明"
                  description="依系統資安原則，諮詢過程中嚴禁違反此項要求。若同仁於工單或回報中涉及機敏資料，系統將阻斷或要求遮蔽。"
                  style={{ backgroundColor: '#F0F1FA', borderColor: '#D1D3E0' }}
                />
              </div>
            ) : (
              /* Document / FAQ Chunk Display */
              <Card
                title={
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text strong style={{ fontSize: '13px' }}>
                      {selectedCitation.section ? `章節：${selectedCitation.section}` : '引用段落全文'}
                    </Text>
                    <Text type="secondary" style={{ fontSize: '11px' }}>
                      最後維護時間：{selectedCitation.updated_at}
                    </Text>
                  </div>
                }
                size="small"
              >
                <div
                  style={{
                    maxHeight: '420px',
                    overflowY: 'auto',
                    padding: '8px 4px',
                    fontSize: '13.5px',
                    lineHeight: 1.6,
                    color: '#242424',
                  }}
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                    {selectedCitation.content || selectedCitation.snippet}
                  </ReactMarkdown>
                </div>
              </Card>
            )}

            {/* Bottom Actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 12 }}>
              {selectedCitation.download_url && (
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  style={{ backgroundColor: '#107C41' }}
                  onClick={() => window.open(selectedCitation.download_url, '_blank')}
                >
                  下載原始文件檔案
                </Button>
              )}
              {selectedCitation.url && (
                <Button
                  icon={<ExportOutlined />}
                  onClick={() => window.open(selectedCitation.url, '_blank')}
                >
                  在新分頁開啟原文
                </Button>
              )}
              <Button onClick={() => setDrawerOpen(false)}>關閉</Button>
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
};

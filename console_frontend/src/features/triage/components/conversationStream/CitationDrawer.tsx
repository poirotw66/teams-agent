import React from 'react';
import {
  Alert,
  Button,
  Card,
  Drawer,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CopyOutlined,
  DownloadOutlined,
  ExportOutlined,
  FileTextOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CitationItem } from '../../../../shared/api/types';
import { isPolicyCitation } from './citationLookup';

const { Text } = Typography;

interface CitationDrawerProps {
  open: boolean;
  citation: CitationItem | null;
  loadingPreview: boolean;
  onClose: () => void;
  /** Footer close button; may leave citation selected for drawer exit animation. */
  onDismiss: () => void;
  onCopyPath: (path: string) => void;
}

export const CitationDrawer: React.FC<CitationDrawerProps> = ({
  open,
  citation: selectedCitation,
  loadingPreview,
  onClose,
  onDismiss,
  onCopyPath,
}) => (
  <Drawer
    open={open}
    onClose={onClose}
    width={560}
    title={
      selectedCitation ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {isPolicyCitation(selectedCitation) ? (
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
            onClick={() =>
              window.open(selectedCitation.download_url ?? undefined, '_blank')
            }
          >
            下載原檔
          </Button>
        )}
        {selectedCitation?.url && (
          <Button
            size="small"
            icon={<ExportOutlined />}
            onClick={() =>
              window.open(selectedCitation.url ?? undefined, '_blank')
            }
          >
            開啟連結
          </Button>
        )}
      </Space>
    }
  >
    {selectedCitation && (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {isPolicyCitation(selectedCitation) ? (
            <Tag color="volcano" icon={<SafetyCertificateOutlined />}>
              資安政策規範
            </Tag>
          ) : selectedCitation.source_type === 'FAQ' ? (
            <Tag color="green">FAQ 知識庫</Tag>
          ) : (
            <Tag color="blue">文件依據</Tag>
          )}

          {isPolicyCitation(selectedCitation) ? (
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
                  onClick={() => onCopyPath(selectedCitation.source_path!)}
                />
              </Tooltip>
            </div>
          </Card>
        )}

        {selectedCitation.is_stale && (
          <Alert
            type="warning"
            showIcon
            message="版本維護提醒"
            description="此文件已超過 1 年未更新，內容可能與現行作業規範有出入，建議資訊維運人員進行內容校閱或更新知識庫。"
          />
        )}

        {loadingPreview ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin tip="正在獲取版本依據與原檔內容..." />
          </div>
        ) : isPolicyCitation(selectedCitation) ? (
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

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 12 }}>
          {selectedCitation.download_url && (
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              style={{ backgroundColor: '#107C41' }}
              onClick={() =>
                window.open(selectedCitation.download_url ?? undefined, '_blank')
              }
            >
              下載原始文件檔案
            </Button>
          )}
          {selectedCitation.url && (
            <Button
              icon={<ExportOutlined />}
              onClick={() =>
                window.open(selectedCitation.url ?? undefined, '_blank')
              }
            >
              在新分頁開啟原文
            </Button>
          )}
          <Button onClick={onDismiss}>關閉</Button>
        </div>
      </div>
    )}
  </Drawer>
);

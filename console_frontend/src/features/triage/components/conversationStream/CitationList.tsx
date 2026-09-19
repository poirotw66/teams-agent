import React from 'react';
import { Button, Collapse, Space, Tag, Typography } from 'antd';
import {
  DownloadOutlined,
  ExportOutlined,
  EyeOutlined,
  FileTextOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { CitationItem } from '../../../../shared/api/types';
import { isPolicyCitation } from './citationLookup';

const { Text } = Typography;

interface CitationListProps {
  citations: CitationItem[];
  onOpenCitation: (cite: CitationItem) => void;
}

export const CitationList: React.FC<CitationListProps> = ({
  citations,
  onOpenCitation,
}) => (
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
                當時 AI 檢索與引用依據 ({citations.length} 份依據)
              </Text>
            </Space>
          ),
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {citations.map((cite, idx) => {
                const isPolicy = isPolicyCitation(cite);

                return (
                  <div
                    key={idx}
                    className="teams-card-hover"
                    onClick={() => onOpenCitation(cite)}
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
                            onOpenCitation(cite);
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
                              window.open(cite.download_url ?? undefined, '_blank');
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
                              window.open(cite.url ?? undefined, '_blank');
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
);

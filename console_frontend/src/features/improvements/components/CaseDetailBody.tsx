import React from 'react';
import { Card, Col, Descriptions, Row, Space, Table, Typography, Button } from 'antd';
import { EvidenceRef } from '../../../shared/api/types';
import { StatusTag } from '../../../shared/ui/StatusTag';
import { CaseRecord } from '../hooks/useCaseDetail';

const { Text, Paragraph } = Typography;

const evidenceColumns = [
  {
    title: '證據來源種類',
    dataIndex: 'source_type',
    key: 'source_type',
    render: (type: string) => {
      switch (type) {
        case 'document_draft':
          return '修正文件草稿';
        case 'faq_draft':
          return '修正 FAQ 草稿';
        case 'quality_candidate':
          return '來源問題候選';
        case 'observation_metric':
          return '上線成效指標';
        default:
          return type;
      }
    },
  },
  {
    title: '項目識別碼 (ID)',
    dataIndex: 'source_id',
    key: 'source_id',
    render: (sid: string) => <Text code>{sid}</Text>,
  },
  {
    title: '關係關聯',
    dataIndex: 'relation',
    key: 'relation',
    render: (rel: string) => <Text>{rel}</Text>,
  },
  {
    title: '有效性驗證',
    dataIndex: 'validity',
    key: 'validity',
    render: (validity: string) => <StatusTag status={validity} type="evidence" />,
  },
  {
    title: '取得時間',
    dataIndex: 'retrieved_at',
    key: 'retrieved_at',
    render: (time: string) => (
      <Text style={{ fontSize: '12px' }}>
        {new Date(time).toLocaleString('zh-TW', { hour12: false })}
      </Text>
    ),
  },
];

export type CaseDetailBodyProps = {
  caseData: CaseRecord;
  evidenceRefs: EvidenceRef[];
  openingSource: boolean;
  onOpenConversation: (conversationId: string) => void;
  onOpenDocument: (documentId: string) => void;
};

export const CaseDetailBody: React.FC<CaseDetailBodyProps> = ({
  caseData,
  evidenceRefs,
  openingSource,
  onOpenConversation,
  onOpenDocument,
}) => {
  return (
    <>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={16}>
          <Card title="案件說明與處理脈絡" style={{ borderRadius: 8 }}>
            <Paragraph style={{ whiteSpace: 'pre-wrap' }}>
              {caseData.description || '無詳細說明'}
            </Paragraph>

            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label="問題分類">
                {caseData.issue_type_id || '未分類'}
              </Descriptions.Item>
              <Descriptions.Item label="優先等級">
                {caseData.priority || 'NORMAL'}
              </Descriptions.Item>
              <Descriptions.Item label="指派人員">
                {caseData.assignee_id || '尚未指派'}
              </Descriptions.Item>
              <Descriptions.Item label="目標完成日">
                {caseData.target_due_at
                  ? new Date(caseData.target_due_at).toLocaleDateString('zh-TW')
                  : '無'}
              </Descriptions.Item>
              <Descriptions.Item label="結案類型">
                {caseData.resolution_type || '尚未結案'}
              </Descriptions.Item>
              <Descriptions.Item label="結案/終止理由">
                {caseData.resolution_reason || '無'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        <Col xs={24} md={8}>
          <Card title="線上成效觀察數據" style={{ borderRadius: 8 }}>
            {caseData.observation_started_at ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="觀察起算時間">
                  {new Date(caseData.observation_started_at).toLocaleString('zh-TW', {
                    hour12: false,
                  })}
                </Descriptions.Item>
                <Descriptions.Item label="最新指標更新">
                  {caseData.observation_updated_at
                    ? new Date(caseData.observation_updated_at).toLocaleString('zh-TW', {
                        hour12: false,
                      })
                    : '尚未更新'}
                </Descriptions.Item>
                <Descriptions.Item label="觀察結論">
                  <Text strong>
                    {caseData.observation_latest?.verdict ||
                      '持續觀察中，目前指標符合預期'}
                  </Text>
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Text type="secondary">
                案件尚未進入觀察階段。修正內容發布並生效後將自動啟動成效統計。
              </Text>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="原對話與原檔追溯" style={{ borderRadius: 8 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>關聯對話</Text>
            <div style={{ marginTop: 8 }}>
              {(caseData.conversation_refs || []).length ? (
                <Space wrap>
                  {(caseData.conversation_refs as string[]).map((conversationId) => (
                    <Button
                      key={conversationId}
                      onClick={() => void onOpenConversation(conversationId)}
                    >
                      開啟對話 {conversationId}
                    </Button>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">尚無關聯對話</Text>
              )}
            </div>
          </div>
          <div>
            <Text strong>關聯知識文件／原檔</Text>
            <div style={{ marginTop: 8 }}>
              {(caseData.document_ids || []).length ? (
                <Space wrap>
                  {(caseData.document_ids as string[]).map((documentId) => (
                    <Button
                      key={documentId}
                      type="primary"
                      loading={openingSource}
                      onClick={() => void onOpenDocument(documentId)}
                    >
                      開啟原檔 {documentId}
                    </Button>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">尚未關聯知識文件</Text>
              )}
            </div>
          </div>
        </Space>
      </Card>

      <Card
        title="可追溯證據清單 (Evidence Trace)"
        style={{ borderRadius: 8 }}
        extra={
          <Text type="secondary" style={{ fontSize: '12px' }}>
            閉環驗收必備證據核對
          </Text>
        }
      >
        <Table
          dataSource={evidenceRefs}
          columns={evidenceColumns}
          rowKey={(row: EvidenceRef) => `${row.source_type}:${row.source_id}`}
          pagination={false}
          locale={{ emptyText: '目前無關聯證據' }}
        />
      </Card>
    </>
  );
};

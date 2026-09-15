import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Row,
  Col,
  Steps,
  Table,
  Button,
  Space,
  Typography,
  Alert,
  Descriptions,
  Modal,
  Form,
  Input,
  Select,
  message,
  Breadcrumb,
  Spin,
} from 'antd';
import {
  ArrowLeftOutlined,
  FileAddOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  AuditOutlined,
  SyncOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiClient } from '../../../shared/api/client';
import {
  WorkflowDetailResponse,
  EvidenceRef,
} from '../../../shared/api/types';
import { StatusTag } from '../../../shared/ui/StatusTag';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

export const CaseDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [workflow, setWorkflow] = useState<WorkflowDetailResponse | null>(null);
  const [caseData, setCaseData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Modals state
  const [isDraftModalOpen, setIsDraftModalOpen] = useState<boolean>(false);
  const [isResolveModalOpen, setIsResolveModalOpen] = useState<boolean>(false);
  const [isCloseModalOpen, setIsCloseModalOpen] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const [draftForm] = Form.useForm();
  const [resolveForm] = Form.useForm();
  const [closeForm] = Form.useForm();

  const loadCaseDetail = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [wfRes, caseRes] = await Promise.all([
        apiClient<WorkflowDetailResponse>(`/api/console/workflows/quality_case/${id}`),
        apiClient<any>(`/api/quality-cases/${id}`),
      ]);
      setWorkflow(wfRes);
      setCaseData(caseRes.case || caseRes);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '載入品質案件詳情失敗';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadCaseDetail();
  }, [loadCaseDetail]);

  const currentEtag = caseData?.etag ?? 1;

  // Handle Transition
  const handleTransition = async (
    status: string,
    reason: string | null = null,
    resolutionType: string | null = null
  ) => {
    if (!id) return;
    setSubmitting(true);
    try {
      await apiClient(`/api/quality-cases/${id}/transition`, {
        method: 'POST',
        body: JSON.stringify({
          status,
          reason,
          resolution_type: resolutionType,
          expected_etag: currentEtag,
        }),
      });
      message.success(`狀態已成功更新至：${status}`);
      await loadCaseDetail();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '狀態切換失敗';
      message.error(msg);
      if (err && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 409) {
        // Reload on conflict
        await loadCaseDetail();
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Create Document Draft
  const handleCreateDraft = async (values: { title: string; content: string; notes?: string }) => {
    if (!id) return;
    setSubmitting(true);
    try {
      await apiClient(`/api/quality-cases/${id}/document-draft`, {
        method: 'POST',
        body: JSON.stringify({
          title: values.title,
          content: values.content,
          notes: values.notes || null,
          expected_case_etag: currentEtag,
        }),
      });
      message.success('已成功建立修正文件草稿並關聯至本案件');
      setIsDraftModalOpen(false);
      draftForm.resetFields();
      await loadCaseDetail();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '建立文件草稿失敗';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  // Resolve Modal Submit
  const handleResolveSubmit = async (values: { resolution_type: string; reason: string }) => {
    await handleTransition('RESOLVED', values.reason, values.resolution_type);
    setIsResolveModalOpen(false);
    resolveForm.resetFields();
  };

  // Close / Wont Fix Modal Submit
  const handleCloseSubmit = async (values: { status: string; reason: string }) => {
    await handleTransition(values.status, values.reason, null);
    setIsCloseModalOpen(false);
    closeForm.resetFields();
  };

  // Refresh observation
  const handleRefreshObservation = async () => {
    if (!id) return;
    setSubmitting(true);
    try {
      await apiClient(`/api/quality-cases/${id}/observation/refresh`, {
        method: 'POST',
        body: JSON.stringify({
          expected_etag: currentEtag,
        }),
      });
      message.success('已重新計算最新上線觀察指標');
      await loadCaseDetail();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '更新觀察指標失敗';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && !caseData) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="載入案件詳情中..." />
      </div>
    );
  }

  if (error && !caseData) {
    return (
      <Alert
        type="error"
        showIcon
        message="找不到或無法讀取品質案件"
        description={error}
        action={
          <Button type="primary" onClick={() => navigate('/console-v2/work')}>
            返回我的工作
          </Button>
        }
      />
    );
  }

  const status = String(caseData?.status || 'NEW').toUpperCase();
  const stages = workflow?.stages || [];
  const evidenceRefs = workflow?.evidence_refs || [];

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

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* Breadcrumb & Navigation */}
      <Breadcrumb
        items={[
          {
            title: <Link to="/console-v2/work">我的工作</Link>,
          },
          {
            title: '品質案件改善流程',
          },
          {
            title: id,
          },
        ]}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space size="middle" align="center">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/console-v2/work')}>
            返回工作佇列
          </Button>
          <div>
            <Space align="center" size="middle">
              <Title level={3} style={{ margin: 0 }}>
                {caseData?.title || '品質案件詳情'}
              </Title>
              <StatusTag status={status} />
            </Space>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              案件編號: {id} · 版本 ETag: {currentEtag} · 權責單位: {caseData?.owner_unit_id}
            </Text>
          </div>
        </Space>

        {/* Action Buttons Header */}
        <Space size="small">
          {status === 'NEW' && (
            <Button
              type="primary"
              loading={submitting}
              onClick={() => handleTransition('TRIAGED', '完成初步分流與方向確認')}
            >
              確認分流與方向 (Triage)
            </Button>
          )}

          {status === 'TRIAGED' && (
            <Button
              type="primary"
              loading={submitting}
              onClick={() => handleTransition('IN_PROGRESS', '展開內容修正作業')}
            >
              進入修正階段
            </Button>
          )}

          {(status === 'TRIAGED' || status === 'IN_PROGRESS') && (
            <Button
              type="primary"
              icon={<FileAddOutlined />}
              onClick={() => setIsDraftModalOpen(true)}
            >
              建立文件草稿
            </Button>
          )}

          {status === 'IN_PROGRESS' && (
            <Button
              type="default"
              icon={<AuditOutlined />}
              loading={submitting}
              onClick={() => handleTransition('WAITING_REVIEW', '草稿完成，送交審核與驗證')}
            >
              提交審核驗證
            </Button>
          )}

          {status === 'WAITING_REVIEW' && (
            <Button
              type="primary"
              icon={<EyeOutlined />}
              loading={submitting}
              onClick={() => handleTransition('OBSERVING', '審核通過，進入線上觀察期')}
            >
              開始上線觀察
            </Button>
          )}

          {status === 'OBSERVING' && (
            <>
              <Button
                icon={<SyncOutlined />}
                loading={submitting}
                onClick={handleRefreshObservation}
              >
                重新整理指標
              </Button>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={() => setIsResolveModalOpen(true)}
              >
                驗收結案
              </Button>
            </>
          )}

          {status !== 'RESOLVED' && status !== 'WONT_FIX' && status !== 'DUPLICATE' && (
            <Button
              danger
              icon={<CloseCircleOutlined />}
              onClick={() => setIsCloseModalOpen(true)}
            >
              終止／不予修復
            </Button>
          )}
        </Space>
      </div>

      {/* 5-Stage Workflow Timeline Card */}
      <Card title="改善閉環階段進度" style={{ borderRadius: 8 }}>
        <Steps
          current={stages.findIndex((s) => s.status === 'current')}
          items={stages.map((stage) => {
            let stepStatus: 'wait' | 'process' | 'finish' | 'error' = 'wait';
            if (stage.status === 'completed') stepStatus = 'finish';
            if (stage.status === 'current') stepStatus = 'process';
            if (stage.status === 'failed') stepStatus = 'error';

            return {
              title: stage.title,
              status: stepStatus,
              description: stage.status === 'completed' ? '已驗證通過' : (stage.status === 'current' ? '當前執行中' : '等待前置階段'),
            };
          })}
        />
      </Card>

      {/* Case Details & Root Cause */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={16}>
          <Card title="案件說明與處理脈絡" style={{ borderRadius: 8 }}>
            <Paragraph style={{ whiteSpace: 'pre-wrap' }}>
              {caseData?.description || '無詳細說明'}
            </Paragraph>

            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
              <Descriptions.Item label="問題分類">
                {caseData?.issue_type_id || '未分類'}
              </Descriptions.Item>
              <Descriptions.Item label="優先等級">
                {caseData?.priority || 'NORMAL'}
              </Descriptions.Item>
              <Descriptions.Item label="指派人員">
                {caseData?.assignee_id || '尚未指派'}
              </Descriptions.Item>
              <Descriptions.Item label="目標完成日">
                {caseData?.target_due_at ? new Date(caseData.target_due_at).toLocaleDateString('zh-TW') : '無'}
              </Descriptions.Item>
              <Descriptions.Item label="結案類型">
                {caseData?.resolution_type || '尚未結案'}
              </Descriptions.Item>
              <Descriptions.Item label="結案/終止理由">
                {caseData?.resolution_reason || '無'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        <Col xs={24} md={8}>
          <Card title="線上成效觀察數據" style={{ borderRadius: 8 }}>
            {caseData?.observation_started_at ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="觀察起算時間">
                  {new Date(caseData.observation_started_at).toLocaleString('zh-TW', { hour12: false })}
                </Descriptions.Item>
                <Descriptions.Item label="最新指標更新">
                  {caseData?.observation_updated_at
                    ? new Date(caseData.observation_updated_at).toLocaleString('zh-TW', { hour12: false })
                    : '尚未更新'}
                </Descriptions.Item>
                <Descriptions.Item label="觀察結論">
                  <Text strong>
                    {caseData?.observation_latest?.verdict || '持續觀察中，目前指標符合預期'}
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

      {/* Evidence References Table Card */}
      <Card
        title="可追溯證據清單 (Evidence Trace)"
        style={{ borderRadius: 8 }}
        extra={<Text type="secondary" style={{ fontSize: '12px' }}>閉環驗收必備證據核對</Text>}
      >
        <Table
          dataSource={evidenceRefs}
          columns={evidenceColumns}
          rowKey={(r: EvidenceRef) => `${r.source_type}:${r.source_id}`}
          pagination={false}
          locale={{ emptyText: '目前無關聯證據' }}
        />
      </Card>

      {/* Modal: Create Document Draft */}
      <Modal
        title="建立品質修正文件草稿"
        open={isDraftModalOpen}
        onCancel={() => setIsDraftModalOpen(false)}
        footer={null}
      >
        <Form
          form={draftForm}
          layout="vertical"
          onFinish={handleCreateDraft}
          initialValues={{ title: `修正：${caseData?.title || ''}` }}
        >
          <Form.Item
            name="title"
            label="文件標題"
            rules={[{ required: true, message: '請輸入修正文件標題' }]}
          >
            <Input placeholder="例如：VPN 常見連線失敗排解說明" />
          </Form.Item>
          <Form.Item
            name="content"
            label="修正內容正文 (Markdown)"
            rules={[{ required: true, message: '請輸入修正內容' }]}
          >
            <TextArea rows={6} placeholder="請輸入補充的操作手冊、障礙排除指引或詳細步驟..." />
          </Form.Item>
          <Form.Item name="notes" label="修正緣由說明備註">
            <Input placeholder="說明此草稿如何修正品質案件的問題" />
          </Form.Item>
          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={() => setIsDraftModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                建立並關聯草稿
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Modal: Resolve Case */}
      <Modal
        title="驗收結案確認"
        open={isResolveModalOpen}
        onCancel={() => setIsResolveModalOpen(false)}
        footer={null}
      >
        <Alert
          type="info"
          showIcon
          message="結案驗收要求"
          description="結案時需核對修正內容已發布生效、線上觀察指標穩定，並記錄明確的結案理由。"
          style={{ marginBottom: 16 }}
        />
        <Form
          form={resolveForm}
          layout="vertical"
          onFinish={handleResolveSubmit}
          initialValues={{ resolution_type: 'DOCUMENT_UPDATED' }}
        >
          <Form.Item
            name="resolution_type"
            label="結案處理方式"
            rules={[{ required: true, message: '請選擇結案方式' }]}
          >
            <Select
              options={[
                { value: 'DOCUMENT_UPDATED', label: '知識文件已完成修正並發布' },
                { value: 'FAQ_UPDATED', label: '常見問答 (FAQ) 已更新並生效' },
                { value: 'PROMPT_TUNED', label: 'AI Prompt / 模型參數已調優' },
                { value: 'FIXED', label: '其他經授權之人工驗收修復' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label="結案說明與驗收結論"
            rules={[{ required: true, message: '請輸入結案說明與驗收記錄' }]}
          >
            <TextArea
              rows={4}
              placeholder="說明修正成果、線上觀察天數、負向回饋下降幅度等具體依據..."
            />
          </Form.Item>
          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={() => setIsResolveModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                確認驗收並結案
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Modal: Close Case (Wont Fix / Duplicate) */}
      <Modal
        title="終止或關閉案件"
        open={isCloseModalOpen}
        onCancel={() => setIsCloseModalOpen(false)}
        footer={null}
      >
        <Form
          form={closeForm}
          layout="vertical"
          onFinish={handleCloseSubmit}
          initialValues={{ status: 'WONT_FIX' }}
        >
          <Form.Item
            name="status"
            label="關閉類別"
            rules={[{ required: true, message: '請選擇類別' }]}
          >
            <Select
              options={[
                { value: 'WONT_FIX', label: '不予修復 (非系統問題或不需調整)' },
                { value: 'DUPLICATE', label: '重複案件 (已有其他追蹤中的相同案件)' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label="終止理由"
            rules={[{ required: true, message: '終止或重複案件必須填寫具體原因' }]}
          >
            <TextArea rows={3} placeholder="請輸入不予修復之具體原因，或指向重複之 Canonical 案件編號..." />
          </Form.Item>
          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={() => setIsCloseModalOpen(false)}>取消</Button>
              <Button danger type="primary" htmlType="submit" loading={submitting}>
                確認關閉案件
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
};

import React from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  FormInstance,
  Input,
  Modal,
  Select,
  Space,
  Typography,
} from 'antd';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

type ConversationTurn = {
  turnId?: string | number;
  answerText?: string;
  questionText?: string;
  sourceRefs?: Array<{ sourceRefId?: string; documentId?: string }>;
  documentIds?: string[];
};

export type CaseDetailModalsProps = {
  caseTitle?: string;
  submitting: boolean;
  openingSource: boolean;
  isDraftModalOpen: boolean;
  isResolveModalOpen: boolean;
  isCloseModalOpen: boolean;
  isConversationModalOpen: boolean;
  conversationDetail: Record<string, unknown> | null;
  draftForm: FormInstance;
  resolveForm: FormInstance;
  closeForm: FormInstance;
  onCloseDraft: () => void;
  onCloseResolve: () => void;
  onCloseClose: () => void;
  onCloseConversation: () => void;
  onCreateDraft: (values: { title: string; content: string; notes?: string }) => void;
  onResolveSubmit: (values: { resolution_type: string; reason: string }) => void;
  onCloseSubmit: (values: { status: string; reason: string }) => void;
  onOpenDocument: (documentId: string) => void;
  onOpenSourceRef: (sourceRefId: string) => void;
};

export const CaseDetailModals: React.FC<CaseDetailModalsProps> = ({
  caseTitle,
  submitting,
  openingSource,
  isDraftModalOpen,
  isResolveModalOpen,
  isCloseModalOpen,
  isConversationModalOpen,
  conversationDetail,
  draftForm,
  resolveForm,
  closeForm,
  onCloseDraft,
  onCloseResolve,
  onCloseClose,
  onCloseConversation,
  onCreateDraft,
  onResolveSubmit,
  onCloseSubmit,
  onOpenDocument,
  onOpenSourceRef,
}) => {
  const conversationId =
    typeof conversationDetail?.conversationId === 'string'
      ? conversationDetail.conversationId
      : '';
  const turns = Array.isArray(conversationDetail?.turns)
    ? (conversationDetail.turns as ConversationTurn[])
    : [];

  return (
    <>
      <Modal
        title={conversationDetail ? `對話 ${conversationId}` : '對話詳情'}
        open={isConversationModalOpen}
        onCancel={onCloseConversation}
        footer={null}
        width={720}
      >
        {turns.length ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {turns.map((turn, index) => (
              <Card
                key={String(turn.turnId || index)}
                size="small"
                title={`回合 ${turn.turnId || index + 1}`}
              >
                <Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                  {turn.answerText || turn.questionText || '（無文字內容）'}
                </Paragraph>
                <Space wrap>
                  {(turn.sourceRefs || []).map((source) => (
                    <Button
                      key={source.sourceRefId}
                      type="link"
                      loading={openingSource}
                      onClick={() => {
                        if (source.sourceRefId) {
                          void onOpenSourceRef(source.sourceRefId);
                        }
                      }}
                    >
                      開啟原檔 {source.sourceRefId || source.documentId}
                    </Button>
                  ))}
                  {(turn.documentIds || []).map((documentId) => (
                    <Button
                      key={documentId}
                      type="link"
                      loading={openingSource}
                      onClick={() => void onOpenDocument(documentId)}
                    >
                      依文件開啟 {documentId}
                    </Button>
                  ))}
                </Space>
              </Card>
            ))}
          </Space>
        ) : (
          <Text type="secondary">此對話沒有可顯示的回合資料。</Text>
        )}
      </Modal>

      <Modal
        title="建立品質修正文件草稿"
        open={isDraftModalOpen}
        onCancel={onCloseDraft}
        footer={null}
      >
        <Form
          form={draftForm}
          layout="vertical"
          onFinish={onCreateDraft}
          initialValues={{ title: `修正：${caseTitle || ''}` }}
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
            <TextArea
              rows={6}
              placeholder="請輸入補充的操作手冊、障礙排除指引或詳細步驟..."
            />
          </Form.Item>
          <Form.Item name="notes" label="修正緣由說明備註">
            <Input placeholder="說明此草稿如何修正品質案件的問題" />
          </Form.Item>
          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={onCloseDraft}>取消</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                建立並關聯草稿
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="驗收結案確認"
        open={isResolveModalOpen}
        onCancel={onCloseResolve}
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
          onFinish={onResolveSubmit}
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
              <Button onClick={onCloseResolve}>取消</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                確認驗收並結案
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="終止或關閉案件" open={isCloseModalOpen} onCancel={onCloseClose} footer={null}>
        <Form
          form={closeForm}
          layout="vertical"
          onFinish={onCloseSubmit}
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
            <TextArea
              rows={3}
              placeholder="請輸入不予修復之具體原因，或指向重複之 Canonical 案件編號..."
            />
          </Form.Item>
          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={onCloseClose}>取消</Button>
              <Button danger type="primary" htmlType="submit" loading={submitting}>
                確認關閉案件
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

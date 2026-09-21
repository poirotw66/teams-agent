import React, { useState, useEffect } from 'react';
import {
  Drawer,
  Form,
  Input,
  Select,
  Button,
  Space,
  Typography,
  Alert,
  message,
  Divider,
} from 'antd';
import {
  ThunderboltOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import {
  describeMutationError,
  isFormValidationError,
} from '../../../shared/api/mutationErrors';

const { Text, Title } = Typography;
const { TextArea } = Input;

export interface QuickFaqInitialData {
  id?: string;
  question: string;
  oldAnswer?: string;
  newAnswer?: string;
  category: string;
  citationTitle?: string;
  resolveConversationId?: string;
}

interface QuickFaqDrawerProps {
  open: boolean;
  onClose: () => void;
  initialData?: QuickFaqInitialData | null;
  onSaved?: () => void;
}

export const QuickFaqDrawer: React.FC<QuickFaqDrawerProps> = ({
  open,
  onClose,
  initialData,
  onSaved,
}) => {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState<boolean>(false);

  useEffect(() => {
    if (open) {
      if (initialData) {
        form.setFieldsValue({
          question: initialData.question,
          answer: initialData.newAnswer || initialData.oldAnswer || '',
          category: initialData.category || '網路通訊',
        });
      } else {
        form.resetFields();
        form.setFieldsValue({
          category: '網路通訊',
        });
      }
    }
  }, [open, initialData, form]);

  const handleSubmit = async () => {
    if (saving) {
      return;
    }

    try {
      const values = await form.validateFields();
      setSaving(true);

      await workbenchStore.quickSaveFaq({
        id: initialData?.id,
        question: values.question,
        answer: values.answer,
        category: values.category,
        resolveConversationId: initialData?.resolveConversationId,
      });

      message.success('FAQ 已儲存成功。索引或發布狀態請以知識庫後續狀態為準。');
      onSaved?.();
      onClose();
    } catch (error) {
      if (isFormValidationError(error)) {
        return;
      }
      message.error(describeMutationError(error, 'FAQ 儲存失敗，請稍後再試'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#5B5FC7', fontSize: 18 }} />
          <Title level={5} style={{ margin: 0 }}>
            {initialData?.id ? '快速修訂 FAQ' : '快速新增 FAQ'}
          </Title>
        </Space>
      }
      placement="right"
      width={520}
      onClose={onClose}
      open={open}
      extra={
        <Space>
          <Button onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={saving}
            onClick={handleSubmit}
            style={{ backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' }}
          >
            儲存 FAQ
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        message="儲存後確認"
        description="送出後會等待伺服器確認寫入。向量索引或 Teams 生效時間依後端實際狀態為準，不以本畫面假設即刻同步。"
        style={{ marginBottom: 20 }}
      />

      {initialData?.citationTitle && (
        <div style={{ marginBottom: 16, padding: '10px 14px', background: '#F0F1FA', border: '1px solid #D1D3E0', borderRadius: 6 }}>
          <Text type="secondary" style={{ fontSize: '12px' }}>關聯之過期引用手冊：</Text>
          <div style={{ fontWeight: 'bold', color: '#5B5FC7' }}>{initialData.citationTitle}</div>
        </div>
      )}

      {initialData?.oldAnswer && (
        <div style={{ marginBottom: 16 }}>
          <Text strong type="danger">當時機器人的錯誤/舊回答：</Text>
          <div
            style={{
              padding: '8px 12px',
              backgroundColor: '#FDF3F4',
              border: '1px solid #F6CCD2',
              borderRadius: 6,
              fontSize: '13px',
              marginTop: 4,
              color: '#C4314B',
            }}
          >
            {initialData.oldAnswer}
          </div>
        </div>
      )}

      <Form form={form} layout="vertical">
        <Form.Item
          name="question"
          label={<Text strong>同仁常見問法（問題題目）</Text>}
          rules={[{ required: true, message: '請輸入同仁的問法' }]}
        >
          <Input placeholder="例：差勤系統網址是什麼？ / 怎麼請假？" />
        </Form.Item>

        <Form.Item
          name="category"
          label={<Text strong>業務分類</Text>}
          rules={[{ required: true, message: '請選擇所屬業務分類' }]}
        >
          <Select
            options={[
              { label: '業務交易系統 (大州/樹精靈/XQ/艾揚)', value: '業務交易系統' },
              { label: '網路通訊 (VPN / 跳板機 / FortiClient)', value: '網路通訊' },
              { label: '帳號安全 (金控入口網 / AD / CTeam / Gitlab)', value: '帳號安全' },
              { label: '通訊協作 (Webex / IP話機)', value: '通訊協作' },
              { label: '電子郵件 (行動裝置 Outlook)', value: '電子郵件' },
              { label: 'IT服務指引 (通報格式 / 權限申請)', value: 'IT服務指引' },
            ]}
          />
        </Form.Item>

        <Form.Item
          name="answer"
          label={<Text strong>正確標準解答內容（支援連結與操作說明）</Text>}
          rules={[{ required: true, message: '請輸入正確解答' }]}
        >
          <TextArea
            rows={5}
            placeholder="請輸入給同仁的正確標準回答內容或最新系統網址..."
          />
        </Form.Item>
      </Form>

      <Divider />
      <div style={{ textAlign: 'center' }}>
        <Text type="secondary" style={{ fontSize: '12px' }}>
          提示：儲存成功後，可前往「知識手冊與問答」頁以 Playground 驗證效果。
        </Text>
      </div>
    </Drawer>
  );
};

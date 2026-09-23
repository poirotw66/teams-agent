import React, { useState, useEffect } from 'react';
import { Modal, Form, Input, Select, Typography, Alert, message, Space } from 'antd';
import { FileDoneOutlined } from '@ant-design/icons';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import {
  describeMutationError,
  isFormValidationError,
} from '../../../shared/api/mutationErrors';

const { Text } = Typography;
const { TextArea } = Input;

export interface EscalateTicketInitialData {
  conversationId?: string;
  reporterName: string;
  reporterDept: string;
  reporterExt?: string;
  title: string;
  category?: 'HARDWARE' | 'ACCESS' | 'NETWORK' | 'SOFTWARE';
  suggestedTeam?: string;
  chatSnippet?: string;
}

interface EscalateTicketModalProps {
  open: boolean;
  onClose: () => void;
  initialData?: EscalateTicketInitialData | null;
  onEscalated?: (ticketNumber: string) => void;
}

export const EscalateTicketModal: React.FC<EscalateTicketModalProps> = ({
  open,
  onClose,
  initialData,
  onEscalated,
}) => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState<boolean>(false);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        reporterName: initialData?.reporterName || '',
        reporterDept: initialData?.reporterDept || '',
        reporterExt: initialData?.reporterExt || '',
        title: initialData?.title || '',
        category: initialData?.category || 'HARDWARE',
        assignedTeam: initialData?.suggestedTeam || '現場硬體組',
        notes: initialData?.chatSnippet ? `【來自 Teams 對話節錄】\n${initialData.chatSnippet}` : '',
      });
    }
  }, [open, initialData, form]);

  const handleSubmit = async () => {
    if (submitting) {
      return;
    }

    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const ticket = await workbenchStore.escalateTicket({
        conversationId: initialData?.conversationId,
        title: values.title,
        reporterName: values.reporterName,
        reporterDept: values.reporterDept,
        reporterExt: values.reporterExt,
        category: values.category,
        assignedTeam: values.assignedTeam,
        notes: values.notes,
      });

      message.success(
        `已成功開立實體 IT 工單 [${ticket.ticket_number}] 並派工至「${values.assignedTeam}」`,
      );
      onEscalated?.(ticket.ticket_number);
      onClose();
    } catch (error) {
      if (isFormValidationError(error)) {
        return;
      }
      message.error(describeMutationError(error, '開立工單失敗，請稍後再試'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={
        <span>
          <FileDoneOutlined style={{ color: '#5B5FC7', marginRight: 8 }} />
          轉開實體 IT 報修單（Jira / 內部工單派工）
        </span>
      }
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      confirmLoading={submitting}
      okText="確認送出開單"
      cancelText="取消"
      okButtonProps={{ style: { backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' } }}
      width={600}
    >
      <Alert
        type="info"
        showIcon
        message="對話上下文自動帶入"
        description="系統已自動自 Teams 對話中提取同仁姓名、部門與問題摘要，無需客服手動重複謄打。"
        style={{ marginBottom: 16 }}
      />

      <Form form={form} layout="vertical">
        <Space style={{ width: '100%' }} size="middle">
          <Form.Item
            name="reporterName"
            label={<Text strong>報修同仁</Text>}
            rules={[{ required: true }]}
            style={{ width: 160 }}
          >
            <Input />
          </Form.Item>

          <Form.Item
            name="reporterDept"
            label={<Text strong>所屬部門</Text>}
            rules={[{ required: true }]}
            style={{ width: 160 }}
          >
            <Input />
          </Form.Item>

          <Form.Item
            name="reporterExt"
            label={<Text strong>分機</Text>}
            style={{ width: 120 }}
          >
            <Input placeholder="例: 3312" />
          </Form.Item>
        </Space>

        <Form.Item
          name="title"
          label={<Text strong>工單問題主旨 (AI 已自動提煉)</Text>}
          rules={[{ required: true, message: '請輸入問題主旨' }]}
        >
          <Input />
        </Form.Item>

        <Space style={{ width: '100%' }} size="middle">
          <Form.Item
            name="category"
            label={<Text strong>工單分類</Text>}
            rules={[{ required: true }]}
            style={{ width: 220 }}
          >
            <Select
              options={[
                { label: '硬體維護 (筆電/螢幕/印表機)', value: 'HARDWARE' },
                { label: '系統權限 (ERP/網域帳號)', value: 'ACCESS' },
                { label: '網路實體 (機房線路/Wi-Fi AP)', value: 'NETWORK' },
                { label: '專案軟體 (差勤/人資系統)', value: 'SOFTWARE' },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="assignedTeam"
            label={<Text strong>指派負責組別</Text>}
            rules={[{ required: true }]}
            style={{ width: 220 }}
          >
            <Select
              options={[
                { label: '現場硬體組 (桌邊支援)', value: '現場硬體組' },
                { label: '系統應用組 (業務系統/ERP)', value: '系統應用組' },
                { label: '網路工程組 (線路/VPN機房)', value: '網路工程組' },
                { label: '資訊客服二線組', value: '資訊客服二線組' },
              ]}
            />
          </Form.Item>
        </Space>

        <Form.Item
          name="notes"
          label={<Text strong>問題描述與對話節錄 (自動夾帶)</Text>}
        >
          <TextArea rows={4} />
        </Form.Item>
      </Form>
    </Modal>
  );
};

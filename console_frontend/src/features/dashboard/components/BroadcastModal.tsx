import React, { useState } from 'react';
import { Modal, Form, Input, Select, Typography, Alert, message } from 'antd';
import { NotificationOutlined } from '@ant-design/icons';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import {
  describeMutationError,
  isFormValidationError,
} from '../../../shared/api/mutationErrors';

const { Text } = Typography;
const { TextArea } = Input;

interface BroadcastModalProps {
  open: boolean;
  onClose: () => void;
  defaultTopic?: string;
  onBroadcastSet?: () => void;
}

export const BroadcastModal: React.FC<BroadcastModalProps> = ({
  open,
  onClose,
  defaultTopic,
  onBroadcastSet,
}) => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState<boolean>(false);

  const handleSubmit = async () => {
    if (submitting) {
      return;
    }

    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const result = await workbenchStore.setSpikeBroadcast(
        values.message,
        Number(values.durationHours),
      );
      message.success(`臨時廣播已啟用，預計到期：${result.expiresAt}`);
      onBroadcastSet?.();
      onClose();
    } catch (error) {
      if (isFormValidationError(error)) {
        return;
      }
      message.error(describeMutationError(error, '廣播啟用失敗，請稍後再試'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={
        <span>
          <NotificationOutlined style={{ color: '#B78800', marginRight: 8 }} />
          設定 Teams 機器人臨時置頂快答 / 突發公告
        </span>
      }
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      confirmLoading={submitting}
      okText="啟用廣播"
      cancelText="取消"
      okButtonProps={{
        style: { backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' },
        disabled: submitting,
      }}
      cancelButtonProps={{ disabled: submitting }}
    >
      <Alert
        type="warning"
        showIcon
        message="啟用前請確認"
        description="送出後會等待伺服器確認。成功訊息會顯示後端回傳的到期時間；失敗時保留表單內容以便重試。"
        style={{ marginBottom: 16 }}
      />

      <Form
        form={form}
        layout="vertical"
        initialValues={{
          durationHours: '2',
          message: defaultTopic
            ? `資訊處已知悉 ${defaultTopic} 異常狀況，目前工程師正在緊急切換備援處理中，預計 1 小時內修復，請同仁暫勿重複進線報修，造成不便敬請見諒！`
            : '',
        }}
      >
        <Form.Item
          name="message"
          label={<Text strong>機器人優先秒回之廣播公告內容</Text>}
          rules={[{ required: true, message: '請輸入公告內容' }]}
        >
          <TextArea rows={4} placeholder="請輸入欲推播給同仁的即時說明..." />
        </Form.Item>

        <Form.Item
          name="durationHours"
          label={<Text strong>廣播有效時限（到期後自動恢復正常問答）</Text>}
          rules={[{ required: true }]}
        >
          <Select
            options={[
              { label: '1 小時 (暫時性斷線或重啟)', value: '1' },
              { label: '2 小時 (標準機房事故排查)', value: '2' },
              { label: '4 小時 (大型系統維護作業)', value: '4' },
              { label: '全天 (直到手動關閉)', value: '24' },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
};

import React, { useState } from 'react';
import { Modal, Form, Input, Select, Typography, Alert, message } from 'antd';
import { NotificationOutlined } from '@ant-design/icons';
import { workbenchStore } from '../../../shared/api/workbenchStore';

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
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      workbenchStore.setSpikeBroadcast(values.message, Number(values.durationHours));
      message.success('已啟用 Teams 機器人置頂快答！相關問題將優先秒回此訊息，攔截重複進線。');
      onBroadcastSet?.();
      onClose();
    } catch {
      // Validation error
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
      okText="立即啟用廣播快答"
      cancelText="取消"
      okButtonProps={{ style: { backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' } }}
    >
      <Alert
        type="warning"
        showIcon
        message="智能進線攔截機制"
        description="啟用後，只要同仁在 Teams 問到與此事件相關的關鍵字，機器人將優先直接回覆這段廣播，不查閱一般文件，避免客服被重複進線灌爆。"
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

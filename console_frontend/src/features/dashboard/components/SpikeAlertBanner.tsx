import React from 'react';
import { Alert, Button, Space, Typography, message } from 'antd';
import {
  NotificationOutlined,
  AlertOutlined,
  SendOutlined,
  CloseCircleOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { SpikeAlertItem } from '../../../shared/api/types';

const { Text } = Typography;

interface SpikeAlertBannerProps {
  alert: SpikeAlertItem | null;
  onViewConversations: (topic: string) => void;
  onOpenBroadcastModal: () => void;
  onDismiss: () => void;
}

export const SpikeAlertBanner: React.FC<SpikeAlertBannerProps> = ({
  alert,
  onViewConversations,
  onOpenBroadcastModal,
  onDismiss,
}) => {
  if (!alert || !alert.is_active) {
    return null;
  }

  const handleNotifyNetworkTeam = () => {
    message.success('已發送緊急通報至網路與機房維運團隊 Teams 頻道！');
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <Alert
        type="warning"
        showIcon
        icon={<AlertOutlined style={{ fontSize: 20, color: '#b78800' }} />}
        message={
          <Space direction="horizontal" size="middle" style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <div>
              <Text strong style={{ fontSize: '15px', color: '#8a6605' }}>
                即時突發事件雷達：過去 {alert.window_minutes} 分鐘內有 {alert.affected_count} 人詢問「{alert.topic}」
              </Text>
              {alert.active_broadcast && (
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: '12px', color: '#616161' }}>
                    目前 Teams 機器人已啟用置頂快答（有效至 {alert.active_broadcast.expires_at}）：
                    「{alert.active_broadcast.message}」
                  </Text>
                </div>
              )}
            </div>

            <Space wrap size="small">
              <Button
                size="small"
                type="primary"
                ghost
                icon={<RightOutlined />}
                onClick={() => onViewConversations(alert.topic)}
                style={{ borderColor: '#5b5fc7', color: '#5b5fc7' }}
              >
                查看 {alert.affected_count} 筆對話
              </Button>
              <Button
                size="small"
                type="primary"
                icon={<NotificationOutlined />}
                onClick={onOpenBroadcastModal}
                style={{ backgroundColor: '#5b5fc7', borderColor: '#5b5fc7' }}
              >
                設定機器人臨時置頂快答
              </Button>
              <Button
                size="small"
                icon={<SendOutlined />}
                onClick={handleNotifyNetworkTeam}
              >
                通報網路組
              </Button>
              <Button
                size="small"
                type="text"
                icon={<CloseCircleOutlined />}
                onClick={onDismiss}
              >
                關閉警報
              </Button>
            </Space>
          </Space>
        }
        style={{
          border: '1px solid #ffe699',
          backgroundColor: '#fff9e6',
          borderRadius: 8,
          padding: '12px 18px',
        }}
      />
    </div>
  );
};

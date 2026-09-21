import React from 'react';
import { Alert, Button, Space, Typography } from 'antd';
import {
  NotificationOutlined,
  AlertOutlined,
  CloseCircleOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { useCan } from '@refinedev/core';
import { SpikeAlertItem } from '../../../shared/api/types';
import { CONSOLE_WRITE_ACTIONS } from '../../../app/routing/routeRegistry';

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
  const { data: canBroadcast } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.broadcastWrite.resource,
    action: CONSOLE_WRITE_ACTIONS.broadcastWrite.action,
  });

  if (!alert || !alert.is_active) {
    return null;
  }

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
              {canBroadcast?.can ? (
                <Button
                  size="small"
                  type="primary"
                  icon={<NotificationOutlined />}
                  onClick={onOpenBroadcastModal}
                  style={{ backgroundColor: '#5b5fc7', borderColor: '#5b5fc7' }}
                >
                  設定機器人臨時置頂快答
                </Button>
              ) : null}
              <Button
                size="small"
                type="text"
                icon={<CloseCircleOutlined />}
                onClick={onDismiss}
                style={{ color: '#8c8c8c' }}
              >
                關閉提醒
              </Button>
            </Space>
          </Space>
        }
      />
    </div>
  );
};

import React from 'react';
import { Row, Col, Card, Statistic, Typography, Skeleton, Alert, Button } from 'antd';
import {
  MessageOutlined,
  CheckCircleOutlined,
  FileDoneOutlined,
  SmileOutlined,
  AlertOutlined,
  ArrowUpOutlined,
} from '@ant-design/icons';
import { DashboardKpiMetrics } from '../../../shared/api/types';

const { Text } = Typography;

export type KpiLoadState = 'loading' | 'error' | 'ready';

interface KpiCardsProps {
  metrics: DashboardKpiMetrics;
  loadState?: KpiLoadState;
  errorMessage?: string;
  onRetry?: () => void;
  onSelectUrgent?: () => void;
}

export const KpiCards: React.FC<KpiCardsProps> = ({
  metrics,
  loadState = 'ready',
  errorMessage,
  onRetry,
  onSelectUrgent,
}) => {
  if (loadState === 'loading') {
    return (
      <Row gutter={[16, 16]}>
        {Array.from({ length: 5 }).map((_, index) => (
          <Col key={`kpi-skeleton-${index}`} xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
            <Card style={{ borderRadius: 10 }}>
              <Skeleton active paragraph={{ rows: 2 }} title={{ width: '60%' }} />
            </Card>
          </Col>
        ))}
      </Row>
    );
  }

  if (loadState === 'error') {
    return (
      <Alert
        type="error"
        showIcon
        message="無法載入營運 KPI"
        description={errorMessage || 'overview 資料來源失敗，以下不會以 0 件假裝完成。'}
        action={
          onRetry ? (
            <Button size="small" onClick={onRetry}>
              重試 overview
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
        <Card hoverable className="teams-card-hover" style={{ borderRadius: 10, borderLeft: '4px solid #5b5fc7' }}>
          <Statistic
            title={<Text strong style={{ color: '#616161', fontSize: '13px' }}>今日諮詢總量</Text>}
            value={metrics.total_inquiries_today}
            suffix={<span style={{ fontSize: '14px', color: '#616161' }}>件</span>}
            prefix={<MessageOutlined style={{ color: '#5b5fc7', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            {metrics.inquiries_trend_percentage !== 0 ? (
              <Text type="secondary" style={{ fontSize: '12px', color: '#107c41' }}>
                <ArrowUpOutlined style={{ color: '#107c41', marginRight: 4 }} />
                較昨日 {metrics.inquiries_trend_percentage > 0 ? `+${metrics.inquiries_trend_percentage}%` : `${metrics.inquiries_trend_percentage}%`}
              </Text>
            ) : (
              <Text type="secondary" style={{ fontSize: '12px' }}>
                進線量常態穩定
              </Text>
            )}
          </div>
        </Card>
      </Col>

      <Col xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
        <Card hoverable className="teams-card-hover" style={{ borderRadius: 10, borderLeft: '4px solid #107c41' }}>
          <Statistic
            title={<Text strong style={{ color: '#616161', fontSize: '13px' }}>AI 自動解決率</Text>}
            value={metrics.ai_resolution_rate}
            suffix={<span style={{ fontSize: '14px', color: '#616161' }}>%</span>}
            precision={1}
            prefix={<CheckCircleOutlined style={{ color: '#107c41', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              {metrics.ai_resolved_count} 件自主解答完成
            </Text>
          </div>
        </Card>
      </Col>

      <Col xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
        <Card hoverable className="teams-card-hover" style={{ borderRadius: 10, borderLeft: '4px solid #6264a7' }}>
          <Statistic
            title={<Text strong style={{ color: '#616161', fontSize: '13px' }}>轉派實體工單</Text>}
            value={metrics.escalated_ticket_count}
            suffix={<span style={{ fontSize: '14px', color: '#616161' }}>件</span>}
            prefix={<FileDoneOutlined style={{ color: '#6264a7', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              現場硬體與權限派工單
            </Text>
          </div>
        </Card>
      </Col>

      <Col xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
        <Card hoverable className="teams-card-hover" style={{ borderRadius: 10, borderLeft: '4px solid #008272' }}>
          <Statistic
            title={<Text strong style={{ color: '#616161', fontSize: '13px' }}>滿意度</Text>}
            value={metrics.satisfaction_rate}
            suffix={<span style={{ fontSize: '14px', color: '#616161' }}>%</span>}
            precision={1}
            prefix={<SmileOutlined style={{ color: '#008272', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              負評 {metrics.negative_feedback_count} 件
            </Text>
          </div>
        </Card>
      </Col>

      <Col xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
        <Card
          hoverable
          className="teams-card-hover"
          style={{ borderRadius: 10, borderLeft: '4px solid #c4314b', cursor: onSelectUrgent ? 'pointer' : 'default' }}
          onClick={onSelectUrgent}
        >
          <Statistic
            title={<Text strong style={{ color: '#616161', fontSize: '13px' }}>待處理緊急件</Text>}
            value={metrics.urgent_attention_count}
            suffix={<span style={{ fontSize: '14px', color: '#616161' }}>件</span>}
            prefix={<AlertOutlined style={{ color: '#c4314b', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              點擊前往今日待辦
            </Text>
          </div>
        </Card>
      </Col>
    </Row>
  );
};

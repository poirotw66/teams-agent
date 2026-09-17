import React from 'react';
import { Row, Col, Card, Statistic, Typography } from 'antd';
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

interface KpiCardsProps {
  metrics: DashboardKpiMetrics;
  onSelectUrgent?: () => void;
}

export const KpiCards: React.FC<KpiCardsProps> = ({ metrics, onSelectUrgent }) => {
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
            title={<Text strong style={{ color: '#616161', fontSize: '13px' }}>同仁滿意度</Text>}
            value={metrics.satisfaction_rate}
            suffix={<span style={{ fontSize: '14px', color: '#616161' }}>%</span>}
            prefix={<SmileOutlined style={{ color: '#008272', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              {metrics.negative_feedback_count > 0 ? `好評滿意 (差評 ${metrics.negative_feedback_count} 件)` : '服務品質良好 (無差評)'}
            </Text>
          </div>
        </Card>
      </Col>

      <Col xs={24} sm={12} lg={4} style={{ flex: '1 1 20%' }}>
        <Card
          hoverable
          className="teams-card-hover"
          onClick={metrics.urgent_attention_count > 0 ? onSelectUrgent : undefined}
          style={{
            borderRadius: 10,
            borderLeft: metrics.urgent_attention_count > 0 ? '4px solid #c4314b' : '4px solid #107c41',
            cursor: metrics.urgent_attention_count > 0 ? 'pointer' : 'default',
            backgroundColor: metrics.urgent_attention_count > 0 ? '#fdf3f4' : undefined,
          }}
        >
          <Statistic
            title={<Text strong style={{ color: metrics.urgent_attention_count > 0 ? '#c4314b' : '#616161', fontSize: '13px' }}>待處理紅字項</Text>}
            value={metrics.urgent_attention_count}
            suffix={<span style={{ fontSize: '14px', color: metrics.urgent_attention_count > 0 ? '#c4314b' : '#616161' }}>筆需介入</span>}
            valueStyle={{ color: metrics.urgent_attention_count > 0 ? '#c4314b' : '#107c41', fontWeight: 'bold' }}
            prefix={<AlertOutlined style={{ color: metrics.urgent_attention_count > 0 ? '#c4314b' : '#107c41', marginRight: 8 }} />}
          />
          <div style={{ marginTop: 8 }}>
            <Text style={{ fontSize: '12px', color: metrics.urgent_attention_count > 0 ? '#c4314b' : '#8a8886' }}>
              {metrics.urgent_attention_count > 0 ? '點擊立即跳轉下方處理' : '目前各項營運指標正常'}
            </Text>
          </div>
        </Card>
      </Col>
    </Row>
  );
};

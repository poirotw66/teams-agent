import React from 'react';
import { Row, Col, Card, Typography, List, Tag, Progress, Space } from 'antd';
import {
  TrophyOutlined,
  CompassOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { TopFrequentTopic, KnowledgeBlindSpot } from '../../../shared/api/types';

const { Text } = Typography;

interface TopDriversPanelProps {
  topTopics: TopFrequentTopic[];
  blindSpots: KnowledgeBlindSpot[];
  onSelectCategory?: (category: string) => void;
}

export const TopDriversPanel: React.FC<TopDriversPanelProps> = ({
  topTopics,
  blindSpots,
  onSelectCategory,
}) => {
  return (
    <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
      <Col xs={24} lg={12}>
        <Card
          title={
            <Space>
              <TrophyOutlined style={{ color: '#B78800' }} />
              <Text strong style={{ fontSize: '15px' }}>
                Top 5 本週最常問 IT 主題
              </Text>
            </Space>
          }
          style={{ borderRadius: 8, height: '100%' }}
        >
          <List
            dataSource={topTopics}
            renderItem={(item) => (
              <List.Item
                style={{
                  padding: '10px 0',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', width: '60%' }}>
                  <Tag
                    style={{
                      minWidth: 24,
                      textAlign: 'center',
                      fontWeight: 'bold',
                      backgroundColor: item.rank === 1 ? '#F0F1FA' : '#F5F5F7',
                      color: item.rank === 1 ? '#5B5FC7' : '#616161',
                      borderColor: item.rank === 1 ? '#D1D3E0' : '#E0E0E6',
                    }}
                  >
                    {item.rank}
                  </Tag>
                  <Text strong style={{ fontSize: '14px' }}>
                    {item.topic}
                  </Text>
                </div>

                <div style={{ width: '35%', textAlign: 'right' }}>
                  <Space size="middle">
                    <Text type="secondary" style={{ fontSize: '12px' }}>
                      {item.count} 次
                    </Text>
                    <span style={{ display: 'inline-block', width: 90 }}>
                      <Progress
                        percent={item.resolution_rate}
                        size="small"
                        strokeColor={item.resolution_rate >= 80 ? '#107C41' : '#C4314B'}
                        format={(percent) => `${percent}%`}
                      />
                    </span>
                  </Space>
                </div>
              </List.Item>
            )}
          />
        </Card>
      </Col>

      <Col xs={24} lg={12}>
        <Card
          title={
            <Space>
              <CompassOutlined style={{ color: '#5B5FC7' }} />
              <Text strong style={{ fontSize: '15px' }}>
                知識庫健康度盲區（最需要補強的類別）
              </Text>
            </Space>
          }
          style={{ borderRadius: 8, height: '100%' }}
        >
          <List
            dataSource={blindSpots}
            renderItem={(spot) => (
              <List.Item
                style={{
                  padding: '12px 0',
                  cursor: onSelectCategory ? 'pointer' : undefined,
                }}
                onClick={() => onSelectCategory?.(spot.category)}
              >
                <div style={{ width: '100%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Space>
                      {spot.status === 'HEALTHY' ? (
                        <CheckCircleOutlined style={{ color: '#107C41' }} />
                      ) : (
                        <WarningOutlined style={{ color: '#B78800' }} />
                      )}
                      <Text strong style={{ fontSize: '14px' }}>
                        {spot.category}
                      </Text>
                    </Space>
                    <Tag
                      style={{
                        backgroundColor:
                          spot.status === 'HEALTHY'
                            ? '#EBF6EC'
                            : spot.status === 'NEEDS_UPDATE'
                            ? '#FFF8E6'
                            : '#FDF3F4',
                        color:
                          spot.status === 'HEALTHY'
                            ? '#107C41'
                            : spot.status === 'NEEDS_UPDATE'
                            ? '#B78800'
                            : '#C4314B',
                        borderColor:
                          spot.status === 'HEALTHY'
                            ? '#BDE3C4'
                            : spot.status === 'NEEDS_UPDATE'
                            ? '#F5D38A'
                            : '#F6CCD2',
                      }}
                    >
                      {spot.status === 'HEALTHY'
                        ? '健全覆蓋'
                        : spot.status === 'NEEDS_UPDATE'
                        ? `差評率 ${spot.negative_rate}% (需更新)`
                        : `轉人工率 ${spot.negative_rate}% (需補圖)`}
                    </Tag>
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <Text type="secondary" style={{ fontSize: '13px' }}>
                      {spot.description}
                    </Text>
                  </div>
                </div>
              </List.Item>
            )}
          />
        </Card>
      </Col>
    </Row>
  );
};

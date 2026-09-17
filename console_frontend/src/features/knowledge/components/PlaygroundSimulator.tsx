import React, { useState } from 'react';
import { Card, Input, Button, Space, Typography, Tag, Avatar, Spin, Divider } from 'antd';
import {
  RobotOutlined,
  SendOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';

const { Text, Paragraph } = Typography;

interface PlaygroundSimulatorProps {
  initialQuery?: string;
}

interface SimulatedResult {
  query: string;
  answer: string;
  matchedTitle: string;
  score: number;
  snippet: string;
  isFaq: boolean;
}

export const PlaygroundSimulator: React.FC<PlaygroundSimulatorProps> = ({ initialQuery }) => {
  const [query, setQuery] = useState<string>(initialQuery || '');
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<SimulatedResult | null>(null);

  React.useEffect(() => {
    if (initialQuery) {
      setQuery(initialQuery);
      executeSimulation(initialQuery);
    }
  }, [initialQuery]);

  const executeSimulation = async (testText: string) => {
    if (!testText.trim()) return;
    setLoading(true);

    try {
      const res = await apiClient<SimulatedResult>('/api/console/workbench/simulate', {
        method: 'POST',
        body: JSON.stringify({ query: testText.trim() }),
      });
      setResult(res);
    } catch (err) {
      console.error('Simulation request failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickChipClick = (text: string) => {
    setQuery(text);
    executeSimulation(text);
  };

  return (
    <Card
      title={
        <Space>
          <RobotOutlined style={{ color: '#5B5FC7' }} />
          <Text strong style={{ fontSize: '14px' }}>
            即時 AI 問答模擬測試 (Playground)
          </Text>
        </Space>
      }
      style={{ borderRadius: 8, height: '100%', display: 'flex', flexDirection: 'column' }}
      styles={{
        body: {
          padding: '16px',
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
        },
      }}
    >
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: '12px' }}>
          在左側修改或上傳後，在此輸入口語測試驗證 AI 命中效果，確認滿意再生效。
        </Text>
      </div>

      {/* Quick Test Chips */}
      <div style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: '12px', color: '#8c8c8c' }}>推薦快速測試：</Text>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
          {[
            'VPN 密碼被鎖怎麼辦？',
            '忘記密碼或密碼需要變更該如何處理？',
            '大州系統功能無法點選怎麼排除？',
            'Gitlab 帳號被鎖定如何解鎖？',
            '通報資訊問題的格式為何？',
          ].map((chip) => (
            <Tag
              key={chip}
              onClick={() => handleQuickChipClick(chip)}
              style={{
                cursor: 'pointer',
                backgroundColor: '#F0F1FA',
                borderColor: '#D1D3E0',
                color: '#5B5FC7',
                borderRadius: 12,
                padding: '2px 10px',
              }}
            >
              {chip}
            </Tag>
          ))}
        </div>
      </div>

      {/* Query Input */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <Input
          placeholder="輸入同仁可能會怎麼問..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={() => executeSimulation(query)}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          loading={loading}
          onClick={() => executeSimulation(query)}
          style={{ backgroundColor: '#5B5FC7', borderColor: '#5B5FC7' }}
        >
          測試
        </Button>
      </div>

      {/* Simulation Result */}
      <div
        style={{
          flex: 1,
          backgroundColor: '#F5F5F7',
          borderRadius: 8,
          border: '1px solid #E0E0E6',
          padding: 14,
          overflowY: 'auto',
          minHeight: 280,
        }}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin tip="AI 正在檢索知識庫並模擬生成回答中..." />
          </div>
        ) : result ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#5B5FC7' }} />
              <Text strong style={{ color: '#242424' }}>
                Teams 機器人模擬回答效果：
              </Text>
            </div>

            <div
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #E1DFDD',
                borderRadius: '8px 8px 8px 0',
                padding: '12px 14px',
                marginBottom: 12,
                boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
              }}
            >
              <Paragraph style={{ margin: 0, whiteSpace: 'pre-line', fontSize: '13px', color: '#242424' }}>
                {result.answer}
              </Paragraph>
            </div>

            <Divider style={{ margin: '12px 0' }} />

            <div
              style={{
                padding: '10px 12px',
                backgroundColor: '#F0F1FA',
                border: '1px solid #D1D3E0',
                borderRadius: 6,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Space>
                  <FileTextOutlined style={{ color: '#5B5FC7' }} />
                  <Text strong style={{ fontSize: '12px', color: '#5B5FC7' }}>
                    {result.matchedTitle}
                  </Text>
                </Space>
                <Tag
                  style={{
                    backgroundColor: '#EBF6EC',
                    color: '#107C41',
                    borderColor: '#BDE3C4',
                  }}
                >
                  相似度 {result.score}%
                </Tag>
              </div>
              <div style={{ marginTop: 4, fontSize: '12px', color: '#616161' }}>
                段落摘錄：「{result.snippet}」
              </div>
            </div>

            <div style={{ marginTop: 10, textAlign: 'right' }}>
              <Tag
                style={{
                  backgroundColor: '#EBF6EC',
                  color: '#107C41',
                  borderColor: '#BDE3C4',
                }}
                icon={<CheckCircleOutlined />}
              >
                已驗證此知識可精準命中
              </Tag>
            </div>
          </div>
        ) : (
          <div style={{ textAlign: 'center', color: '#8c8c8c', paddingTop: 60 }}>
            點擊上方測試題或輸入問題，立刻檢驗 AI 回答效果
          </div>
        )}
      </div>
    </Card>
  );
};

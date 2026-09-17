import React from 'react';
import { Card, Radio, Button, Space, Typography, Divider, Alert, message } from 'antd';
import {
  ThunderboltOutlined,
  FileDoneOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import { ConversationDetail } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';
import { EscalateTicketInitialData } from '../../dashboard/components/EscalateTicketModal';

const { Text } = Typography;

interface TriageActionPanelProps {
  conversation: ConversationDetail | null;
  onOpenQuickFaq: (data: QuickFaqInitialData) => void;
  onOpenEscalateModal: (data: EscalateTicketInitialData) => void;
}

export const TriageActionPanel: React.FC<TriageActionPanelProps> = ({
  conversation,
  onOpenQuickFaq,
  onOpenEscalateModal,
}) => {
  if (!conversation) {
    return null;
  }

  const handleRootCauseChange = (e: any) => {
    workbenchStore.setRootCause(conversation.id, e.target.value);
    message.success('已更新此對話之根因診斷標籤！');
  };

  const handleAddToGoldenEval = () => {
    message.success(`已將「${conversation.reporter_name}」的提問問法加入 Golden Eval 基準測試集！`);
  };

  const handleMarkResolved = () => {
    workbenchStore.resolveConversation(conversation.id);
    message.success('已標記為結案/已排除！');
  };

  const firstUserMsg = conversation.messages.find((m) => m.sender === 'user');
  const botMsg = conversation.messages.find((m) => m.sender === 'bot');
  const citation = botMsg?.citations?.[0];

  return (
    <Card
      title={
        <Space>
          <AuditOutlined style={{ color: '#5B5FC7' }} />
          <Text strong style={{ fontSize: '15px' }}>
            根因診斷與直接處置
          </Text>
        </Space>
      }
      style={{ borderRadius: 8, height: '100%', display: 'flex', flexDirection: 'column' }}
      styles={{
        body: { padding: '16px', flex: 1, overflowY: 'auto', maxHeight: '720px' },
      }}
    >
      <div>
        <Text strong style={{ fontSize: '13px', color: '#595959' }}>
          【快速診斷標籤（單選點擊）】
        </Text>
        <div style={{ marginTop: 8 }}>
          <Radio.Group
            value={conversation.root_cause}
            onChange={handleRootCauseChange}
            style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
          >
            <Radio value="OUTDATED_DOC">
              <Text strong style={{ fontSize: '13px' }}>知識庫過期 / 內容有誤</Text>
              <div style={{ fontSize: '12px', color: '#8c8c8c', marginLeft: 24 }}>
                例：舊版系統網址報 404、規定已更新但手冊未改
              </div>
            </Radio>

            <Radio value="MISSING_KNOWLEDGE">
              <Text strong style={{ fontSize: '13px' }}>知識庫缺漏 (完全無資料)</Text>
              <div style={{ fontSize: '12px', color: '#8c8c8c', marginLeft: 24 }}>
                例：新制度剛推行、外接螢幕借用手續未收錄
              </div>
            </Radio>

            <Radio value="MISUNDERSTOOD">
              <Text strong style={{ fontSize: '13px' }}>意圖理解錯誤 (答非所問)</Text>
              <div style={{ fontSize: '12px', color: '#8c8c8c', marginLeft: 24 }}>
                例：問印表機卻回答會議室螢幕、語音辨識錯誤
              </div>
            </Radio>

            <Radio value="HARDWARE_TICKET">
              <Text strong style={{ fontSize: '13px' }}>屬現場硬體或特殊權限 (需開單)</Text>
              <div style={{ fontSize: '12px', color: '#8c8c8c', marginLeft: 24 }}>
                例：筆電進水、螢幕破裂、高階主管特殊權限
              </div>
            </Radio>
          </Radio.Group>
        </div>
      </div>

      <Divider style={{ margin: '16px 0' }} />

      <div>
        <Text strong style={{ fontSize: '13px', color: '#595959' }}>
          【零公文處置動作】
        </Text>

        <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 12 }}>
          <Button
            type="primary"
            block
            icon={<ThunderboltOutlined />}
            onClick={() =>
              onOpenQuickFaq({
                question: firstUserMsg?.content || conversation.topic_summary,
                oldAnswer: botMsg?.content,
                category: '網路通訊',
                citationTitle: citation?.document_title,
                resolveConversationId: conversation.id,
              })
            }
            style={{ backgroundColor: '#5b5fc7', borderColor: '#5b5fc7', height: '40px', fontWeight: 600 }}
          >
            10 秒修訂此知識 / FAQ
          </Button>

          <Button
            block
            icon={<FileDoneOutlined />}
            onClick={() =>
              onOpenEscalateModal({
                conversationId: conversation.id,
                reporterName: conversation.reporter_name,
                reporterDept: conversation.reporter_dept,
                reporterExt: conversation.reporter_ext,
                title: conversation.topic_summary,
                chatSnippet: firstUserMsg?.content,
              })
            }
            style={{
              borderColor: '#6264a7',
              color: '#6264a7',
              height: '40px',
              fontWeight: 600,
            }}
          >
            轉開實體 IT 報修單 (Jira)
          </Button>

          <Button
            block
            icon={<ExperimentOutlined />}
            onClick={handleAddToGoldenEval}
            style={{ height: '36px' }}
          >
            🧪 加入 Golden Eval 迴歸測試集
          </Button>

          <Button
            block
            icon={<CheckCircleOutlined />}
            onClick={handleMarkResolved}
            style={{ height: '36px' }}
          >
            ✅ 標記結案 / 已排除
          </Button>
        </Space>
      </div>

      <div style={{ marginTop: 20 }}>
        <Alert
          type="success"
          message="閉環成效追蹤"
          description="修訂發布後，下位詢問相同問題之同仁將立即取得最新答案。"
          style={{ fontSize: '12px' }}
        />
      </div>
    </Card>
  );
};

import React, { useState } from 'react';
import { Card, Radio, Button, Space, Typography, Divider, Alert, message } from 'antd';
import {
  ThunderboltOutlined,
  FileDoneOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import { useCan } from '@refinedev/core';
import { ConversationDetail } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { describeMutationError } from '../../../shared/api/mutationErrors';
import { CONSOLE_WRITE_ACTIONS } from '../../../app/routing/routeRegistry';
import { QuickFaqInitialData } from '../../dashboard/components/QuickFaqDrawer';
import { EscalateTicketInitialData } from '../../dashboard/components/EscalateTicketModal';
import { createGoldenEvalCaseFromConversation } from '../api/goldenEvalCases';

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
  const [rootCauseSubmitting, setRootCauseSubmitting] = useState(false);
  const [goldenEvalSubmitting, setGoldenEvalSubmitting] = useState(false);
  const [resolveSubmitting, setResolveSubmitting] = useState(false);

  const { data: canWriteFaq } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.faqWrite.resource,
    action: CONSOLE_WRITE_ACTIONS.faqWrite.action,
  });
  const { data: canEditRootCause } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.conversationRootCause.resource,
    action: CONSOLE_WRITE_ACTIONS.conversationRootCause.action,
  });
  const { data: canResolve } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.conversationResolve.resource,
    action: CONSOLE_WRITE_ACTIONS.conversationResolve.action,
  });
  const { data: canEscalate } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.ticketEscalate.resource,
    action: CONSOLE_WRITE_ACTIONS.ticketEscalate.action,
  });
  const { data: canCreateGoldenEval } = useCan({
    resource: CONSOLE_WRITE_ACTIONS.goldenEvalCreate.resource,
    action: CONSOLE_WRITE_ACTIONS.goldenEvalCreate.action,
  });

  const handleRootCauseChange = async (value: string) => {
    if (!conversation || rootCauseSubmitting || !canEditRootCause?.can) {
      return;
    }
    setRootCauseSubmitting(true);
    try {
      await workbenchStore.setRootCause(
        conversation.id,
        value as
          | 'OUTDATED_DOC'
          | 'MISSING_KNOWLEDGE'
          | 'MISUNDERSTOOD'
          | 'HARDWARE_TICKET',
      );
      message.success('已更新此對話之根因診斷標籤');
    } catch (error) {
      message.error(describeMutationError(error, '根因更新失敗，請稍後再試'));
    } finally {
      setRootCauseSubmitting(false);
    }
  };

  const handleAddToGoldenEval = async () => {
    if (!conversation || goldenEvalSubmitting || !canCreateGoldenEval?.can) {
      return;
    }
    setGoldenEvalSubmitting(true);
    try {
      const created = await createGoldenEvalCaseFromConversation(conversation);
      message.success(
        `已建立 Golden Eval 案例候選（${created.caseId}）。後續審核與納入評測集請至評測頁完成。`,
      );
    } catch (error) {
      message.error(describeMutationError(error, '加入 Golden Eval 失敗，請稍後再試'));
    } finally {
      setGoldenEvalSubmitting(false);
    }
  };

  const handleMarkResolved = async () => {
    if (!conversation || resolveSubmitting || !canResolve?.can) {
      return;
    }
    setResolveSubmitting(true);
    try {
      await workbenchStore.resolveConversation(conversation.id);
      message.success('已標記為結案/已排除');
    } catch (error) {
      message.error(describeMutationError(error, '結案失敗，請稍後再試'));
    } finally {
      setResolveSubmitting(false);
    }
  };

  if (!conversation) {
    return null;
  }

  const firstUserMsg = conversation.messages.find((m) => m.sender === 'user');
  const botMsg = conversation.messages.find((m) => m.sender === 'bot');
  const citation = botMsg?.citations?.[0];
  const actionBusy = rootCauseSubmitting || goldenEvalSubmitting || resolveSubmitting;

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
        body: { padding: '16px', flex: 1, overflowY: 'auto' },
      }}
    >
      <div>
        <Text strong style={{ fontSize: '13px', color: '#595959' }}>
          【快速診斷標籤（單選點擊）】
        </Text>
        <div style={{ marginTop: 8 }}>
          <Radio.Group
            value={conversation.root_cause}
            onChange={(event) => {
              void handleRootCauseChange(event.target.value);
            }}
            disabled={rootCauseSubmitting || !canEditRootCause?.can}
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
          {!canEditRootCause?.can ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message="目前身分沒有根因標記寫入權限"
            />
          ) : null}
        </div>
      </div>

      <Divider style={{ margin: '16px 0' }} />

      <div>
        <Text strong style={{ fontSize: '13px', color: '#595959' }}>
          【處置動作】
        </Text>

        <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 12 }}>
          {canWriteFaq?.can ? (
            <Button
              type="primary"
              block
              icon={<ThunderboltOutlined />}
              disabled={actionBusy}
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
              修訂此知識 / FAQ
            </Button>
          ) : null}

          {canEscalate?.can ? (
            <Button
              block
              icon={<FileDoneOutlined />}
              disabled={actionBusy}
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
          ) : null}

          {canCreateGoldenEval?.can ? (
            <Button
              block
              icon={<ExperimentOutlined />}
              loading={goldenEvalSubmitting}
              disabled={actionBusy && !goldenEvalSubmitting}
              onClick={() => {
                void handleAddToGoldenEval();
              }}
              style={{ height: '36px' }}
            >
              加入 Golden Eval 候選案例
            </Button>
          ) : (
            <Button block disabled style={{ height: '36px' }}>
              Golden Eval 寫入不可用（缺少 ops.evals.write）
            </Button>
          )}

          {canResolve?.can ? (
            <Button
              block
              icon={<CheckCircleOutlined />}
              loading={resolveSubmitting}
              disabled={actionBusy && !resolveSubmitting}
              onClick={() => {
                void handleMarkResolved();
              }}
              style={{ height: '36px' }}
            >
              標記結案 / 已排除
            </Button>
          ) : null}
        </Space>
      </div>

      <div style={{ marginTop: 20 }}>
        <Alert
          type="info"
          message="處置回饋"
          description="所有寫入動作皆在伺服器確認後才顯示成功。Golden Eval 僅建立候選案例，不會自動宣稱已納入正式評測集。"
          style={{ fontSize: '12px' }}
        />
      </div>
    </Card>
  );
};

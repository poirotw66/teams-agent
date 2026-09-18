import React from 'react';
import { Card, Steps } from 'antd';
import { WorkflowStage } from '../../../shared/api/types';

export type CaseWorkflowTimelineProps = {
  stages: WorkflowStage[];
};

function stageStepStatus(
  status: WorkflowStage['status']
): 'wait' | 'process' | 'finish' | 'error' {
  if (status === 'completed') return 'finish';
  if (status === 'current') return 'process';
  if (status === 'failed') return 'error';
  return 'wait';
}

function stageDescription(status: WorkflowStage['status']): string {
  if (status === 'completed') return '已驗證通過';
  if (status === 'current') return '當前執行中';
  return '等待前置階段';
}

export const CaseWorkflowTimeline: React.FC<CaseWorkflowTimelineProps> = ({ stages }) => {
  return (
    <Card title="改善閉環階段進度" style={{ borderRadius: 8 }}>
      <Steps
        current={stages.findIndex((stage) => stage.status === 'current')}
        items={stages.map((stage) => ({
          title: stage.title,
          status: stageStepStatus(stage.status),
          description: stageDescription(stage.status),
        }))}
      />
    </Card>
  );
};

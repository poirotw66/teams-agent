import React from 'react';
import { Tag } from 'antd';

interface StatusTagProps {
  status: string;
  type?: 'stage' | 'case' | 'health' | 'evidence';
}

export const StatusTag: React.FC<StatusTagProps> = ({ status, type = 'case' }) => {
  const normalized = status.toUpperCase();

  if (type === 'stage') {
    switch (status) {
      case 'completed':
        return <Tag color="success">已完成</Tag>;
      case 'current':
        return <Tag color="processing">進行中</Tag>;
      case 'failed':
        return <Tag color="error">未通過</Tag>;
      case 'skipped':
        return <Tag color="default">略過</Tag>;
      default:
        return <Tag color="default">待處理</Tag>;
    }
  }

  if (type === 'health') {
    switch (status.toLowerCase()) {
      case 'ok':
      case 'healthy':
        return <Tag color="success">正常</Tag>;
      case 'degraded':
        return <Tag color="warning">降級運行</Tag>;
      case 'unavailable':
      case 'down':
      case 'unhealthy':
        return <Tag color="error">服務異常</Tag>;
      default:
        return <Tag color="default">{status}</Tag>;
    }
  }

  if (type === 'evidence') {
    switch (status.toLowerCase()) {
      case 'valid':
        return <Tag color="success">有效證據</Tag>;
      case 'stale':
        return <Tag color="warning">過期證據</Tag>;
      case 'revoked':
        return <Tag color="error">已撤銷</Tag>;
      default:
        return <Tag color="default">未知</Tag>;
    }
  }

  // Case statuses
  switch (normalized) {
    case 'NEW':
      return <Tag color="blue">待分流</Tag>;
    case 'TRIAGED':
      return <Tag color="cyan">已確認方向</Tag>;
    case 'IN_PROGRESS':
      return <Tag color="processing">修正中</Tag>;
    case 'WAITING_REVIEW':
      return <Tag color="orange">等待審核</Tag>;
    case 'OBSERVING':
      return <Tag color="purple">上線觀察中</Tag>;
    case 'RESOLVED':
      return <Tag color="success">已驗證結案</Tag>;
    case 'WONT_FIX':
      return <Tag color="default">不予修復</Tag>;
    case 'DUPLICATE':
      return <Tag color="default">重複案件</Tag>;
    default:
      return <Tag>{status}</Tag>;
  }
};

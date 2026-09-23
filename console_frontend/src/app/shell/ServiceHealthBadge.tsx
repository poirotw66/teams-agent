import React, { useCallback, useEffect, useState } from 'react';
import { Tag, Tooltip } from 'antd';
import {
  CheckCircleFilled,
  WarningFilled,
  CloseCircleFilled,
  QuestionCircleFilled,
} from '@ant-design/icons';
import { apiClient } from '../../shared/api/client';

type HealthFetchState = 'loading' | 'ready' | 'error' | 'stale';

type HealthSummaryResponse = {
  overallStatus?: string;
  status?: string;
  generatedAt?: string;
  asOf?: string;
};

const STALE_AFTER_MS = 5 * 60 * 1000;
const POLL_INTERVAL_MS = 60 * 1000;

function pickOverallStatus(payload: HealthSummaryResponse | null): string {
  if (!payload) {
    return 'UNKNOWN';
  }
  return String(payload.overallStatus || payload.status || 'UNKNOWN').toUpperCase();
}

function pickGeneratedAt(payload: HealthSummaryResponse | null): string | null {
  if (!payload) {
    return null;
  }
  const raw = payload.generatedAt || payload.asOf;
  return typeof raw === 'string' && raw.trim() ? raw : null;
}

function formatUpdatedAt(isoOrText: string | null, fetchedAt: number | null): string {
  if (isoOrText) {
    const parsed = Date.parse(isoOrText);
    if (!Number.isNaN(parsed)) {
      return new Date(parsed).toLocaleString('zh-TW', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    }
    return isoOrText;
  }
  if (fetchedAt) {
    return new Date(fetchedAt).toLocaleTimeString('zh-TW', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }
  return '未知';
}

function visualForStatus(status: string, state: HealthFetchState): {
  label: string;
  color: string;
  background: string;
  border: string;
  icon: React.ReactNode;
} {
  if (state === 'loading' && status === 'UNKNOWN') {
    return {
      label: '服務狀態：檢查中',
      color: '#d9d9d9',
      background: 'rgba(140, 140, 140, 0.25)',
      border: 'rgba(140, 140, 140, 0.45)',
      icon: <QuestionCircleFilled style={{ color: '#bfbfbf' }} />,
    };
  }
  if (state === 'error') {
    return {
      label: '服務狀態：無法取得',
      color: '#ffccc7',
      background: 'rgba(196, 49, 75, 0.25)',
      border: 'rgba(196, 49, 75, 0.5)',
      icon: <CloseCircleFilled style={{ color: '#ff7875' }} />,
    };
  }
  if (state === 'stale') {
    return {
      label: `服務狀態：可能過期（${status}）`,
      color: '#ffe58f',
      background: 'rgba(183, 136, 0, 0.25)',
      border: 'rgba(183, 136, 0, 0.5)',
      icon: <WarningFilled style={{ color: '#ffc53d' }} />,
    };
  }
  if (status === 'READY' || status === 'OK' || status === 'HEALTHY') {
    return {
      label: `服務狀態：${status}`,
      color: '#60d98f',
      background: 'rgba(16, 124, 65, 0.2)',
      border: 'rgba(16, 124, 65, 0.4)',
      icon: <CheckCircleFilled style={{ color: '#52c41a' }} />,
    };
  }
  if (status === 'DEGRADED') {
    return {
      label: '服務狀態：DEGRADED',
      color: '#ffe58f',
      background: 'rgba(183, 136, 0, 0.25)',
      border: 'rgba(183, 136, 0, 0.5)',
      icon: <WarningFilled style={{ color: '#ffc53d' }} />,
    };
  }
  return {
    label: `服務狀態：${status || 'UNKNOWN'}`,
    color: '#d9d9d9',
    background: 'rgba(140, 140, 140, 0.25)',
    border: 'rgba(140, 140, 140, 0.45)',
    icon: <QuestionCircleFilled style={{ color: '#bfbfbf' }} />,
  };
}

/**
 * Live health chip backed by /api/health/summary.
 * Never hard-codes a green "normal" status.
 */
export const ServiceHealthBadge: React.FC = () => {
  const [payload, setPayload] = useState<HealthSummaryResponse | null>(null);
  const [state, setState] = useState<HealthFetchState>('loading');
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await apiClient<HealthSummaryResponse>('/api/health/summary');
      setPayload(res);
      setFetchedAt(Date.now());
      setErrorMessage(null);
      setState('ready');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '健康檢查失敗');
      setState((previous) => (previous === 'ready' || previous === 'stale' ? 'stale' : 'error'));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const pollId = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    const staleId = window.setInterval(() => {
      setFetchedAt((current) => {
        if (current && Date.now() - current > STALE_AFTER_MS) {
          setState((previous) => (previous === 'error' ? previous : 'stale'));
        }
        return current;
      });
    }, 15_000);
    return () => {
      window.clearInterval(pollId);
      window.clearInterval(staleId);
    };
  }, [refresh]);

  const status = pickOverallStatus(payload);
  const visual = visualForStatus(status, state);
  const updatedLabel = formatUpdatedAt(pickGeneratedAt(payload), fetchedAt);

  return (
    <Tooltip
      title={
        errorMessage
          ? `最後錯誤：${errorMessage}；最後更新：${updatedLabel}`
          : `最後更新：${updatedLabel}`
      }
    >
      <Tag
        style={{
          backgroundColor: visual.background,
          color: visual.color,
          border: `1px solid ${visual.border}`,
          borderRadius: 12,
          padding: '1px 10px',
          marginInlineEnd: 0,
        }}
        icon={visual.icon}
      >
        {visual.label} · {updatedLabel}
      </Tag>
    </Tooltip>
  );
};

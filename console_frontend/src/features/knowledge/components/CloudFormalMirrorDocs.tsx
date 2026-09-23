import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Table, Tag, Tooltip, Typography, message } from 'antd';
import { CloudOutlined, EyeOutlined } from '@ant-design/icons';
import { apiClient } from '../../../shared/api/client';
import { ManualDocumentItem } from '../../../shared/api/types';
import { KNOWLEDGE_MIRROR_UPDATED_EVENT } from '../lib/knowledgeMirrorEvents';
import {
  KnowledgeMirrorDocument,
  KnowledgeSyncStatus,
  fetchMirrorDocumentPreview,
  mirrorPreviewToManualDocument,
} from '../lib/syncLocalKnowledgeMirror';
import { ChunkInspectorModal } from './ChunkInspectorModal';

const { Text } = Typography;

type KnowledgeStatusResponse = {
  currentReleaseId?: string | null;
  sync?: KnowledgeSyncStatus;
};

type CloudFormalMirrorDocsProps = {
  onTestQuery?: (query: string) => void;
  isCloudConsole?: boolean;
};

export const CloudFormalMirrorDocs: React.FC<CloudFormalMirrorDocsProps> = ({
  onTestQuery,
  isCloudConsole = false,
}) => {
  const [status, setStatus] = useState<KnowledgeStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspectingId, setInspectingId] = useState<string | null>(null);
  const [inspectDoc, setInspectDoc] = useState<ManualDocumentItem | null>(null);
  const [inspectOpen, setInspectOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiClient<KnowledgeStatusResponse>(
        '/api/console/agent-knowledge/status',
      );
      setStatus(data);
      setError(null);
    } catch (err) {
      setStatus(null);
      setError(
        err instanceof Error
          ? err.message
          : isCloudConsole
            ? '無法讀取正式 Agent 目前載入的文件清單。'
            : '無法讀取本機 GCS 鏡像文件清單。',
      );
    }
  }, [isCloudConsole]);

  useEffect(() => {
    void load();
    const onUpdated = () => {
      void load();
    };
    window.addEventListener(KNOWLEDGE_MIRROR_UPDATED_EVENT, onUpdated);
    return () => {
      window.removeEventListener(KNOWLEDGE_MIRROR_UPDATED_EVENT, onUpdated);
    };
  }, [load]);

  const documents = status?.sync?.documents || [];
  const releaseId =
    status?.sync?.loadedReleaseId || status?.currentReleaseId || '—';

  const handleInspect = async (row: KnowledgeMirrorDocument) => {
    const documentId = row.documentId?.trim();
    if (!documentId) {
      message.error('此鏡像文件缺少文件 ID，無法預覽段落。');
      return;
    }
    setInspectingId(documentId);
    try {
      const preview = await fetchMirrorDocumentPreview(documentId);
      setInspectDoc(mirrorPreviewToManualDocument(preview));
      setInspectOpen(true);
    } catch (err) {
      message.error(
        err instanceof Error
          ? `無法載入雲端正式鏡像段落：${err.message}`
          : '無法載入雲端正式鏡像段落。',
      );
    } finally {
      setInspectingId(null);
    }
  };

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        message={isCloudConsole ? '正式 Agent 目前載入清單無法載入' : '雲端正式鏡像清單無法載入'}
        description={error}
      />
    );
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        icon={<CloudOutlined />}
        style={{ marginBottom: 12 }}
        message={
          <span>
            {isCloudConsole
              ? '這是正式 Agent 目前正在服務的 release '
              : '這是本機已同步的雲端正式 release '}
            <Tag color="blue">{releaseId}</Tag>
            {isCloudConsole ? '。' : '，與 Playground Agent 同一份 GCS 鏡像。'}
          </span>
        }
        description={
          <Text type="secondary">
            {isCloudConsole
              ? '這是唯讀狀態：正式問答正在用的已發布版。要新增或刪除請到「知識文件」，發布新 release 後才會換這份清單。'
              : '「預覽段落」讀的是已發布 index/chunks.json，版面與本機測試工作區的切分檢視器相同。這不是 FILE sandbox 重切結果。'}
          </Text>
        }
      />
      <Table
        size="small"
        rowKey={(row) => row.documentId || row.sourcePath || row.title || ''}
        pagination={documents.length > 12 ? { pageSize: 12 } : false}
        dataSource={documents}
        locale={{
          emptyText: isCloudConsole
            ? '正式 Agent 目前沒有已載入文件。請確認已發布 release。'
            : '本機尚無 GCS 鏡像文件。請按「立即同步」。',
        }}
        columns={[
          {
            title: '文件',
            dataIndex: 'title',
            render: (title: string | null | undefined, row) =>
              title || row.documentId || '—',
          },
          {
            title: '文件 ID',
            dataIndex: 'documentId',
            width: 220,
            render: (value?: string | null) => (
              <Text code style={{ fontSize: 12 }}>
                {value || '—'}
              </Text>
            ),
          },
          {
            title: '狀態',
            dataIndex: 'contentState',
            width: 100,
            render: (value?: string | null) =>
              value ? <Tag>{value}</Tag> : '—',
          },
          {
            title: '操作',
            key: 'actions',
            width: 88,
            render: (_: unknown, row: KnowledgeMirrorDocument) => (
              <Tooltip title="預覽段落">
                <Button
                  aria-label="預覽段落"
                  size="small"
                  icon={<EyeOutlined />}
                  loading={inspectingId === row.documentId}
                  onClick={() => void handleInspect(row)}
                />
              </Tooltip>
            ),
          },
        ]}
      />
      <ChunkInspectorModal
        open={inspectOpen}
        document={inspectDoc}
        readOnly
        onClose={() => {
          setInspectOpen(false);
          setInspectDoc(null);
        }}
        onTestQuery={onTestQuery || (() => undefined)}
      />
    </div>
  );
};

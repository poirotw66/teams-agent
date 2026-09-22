import React, { useState } from 'react';
import {
  Upload,
  Button,
  Table,
  Tag,
  Space,
  Typography,
  Select,
  Card,
  Popconfirm,
  Tooltip,
  message,
} from 'antd';
import {
  InboxOutlined,
  UploadOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileTextOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { ManualDocumentItem } from '../../../shared/api/types';
import { workbenchStore } from '../../../shared/api/workbenchStore';
import { ChunkInspectorModal } from './ChunkInspectorModal';
import { DocumentGovernanceActions } from './DocumentGovernanceActions';
import { PublishElapsedLabel } from './PublishElapsedLabel';
import { UploadDocumentModal } from './UploadDocumentModal';
import { readFormalPublishInFlight } from '../lib/formalPublishSession';

const { Dragger } = Upload;
const { Text } = Typography;

const DOCUMENT_STATUS: Record<
  ManualDocumentItem['status'],
  { label: string; color: string }
> = {
  LIVE: { label: '現行生效', color: 'success' },
  DRAFT: { label: '待品質審查', color: 'processing' },
  PARSING: { label: '解析中', color: 'processing' },
  CHUNK_REVIEW: { label: '待品質審查', color: 'processing' },
  IN_REVIEW: { label: '審查中', color: 'warning' },
  APPROVED: { label: '已核准待發布', color: 'cyan' },
  CHANGES_REQUESTED: { label: '待修改', color: 'error' },
  PUBLISHING: { label: '正式發布同步中', color: 'processing' },
  READY: { label: '待啟用', color: 'cyan' },
  FAILED: { label: '處理失敗', color: 'error' },
  ARCHIVED: { label: '已封存', color: 'default' },
};

interface ManualDocsManagerProps {
  documents: ManualDocumentItem[];
  onTestQuery: (query: string) => void;
  selectedCategory?: string | null;
}

export const ManualDocsManager: React.FC<ManualDocsManagerProps> = ({
  documents,
  onTestQuery,
  selectedCategory,
}) => {
  const [uploadModalOpen, setUploadModalOpen] = useState<boolean>(false);
  const [inspectModalOpen, setInspectModalOpen] = useState<boolean>(false);
  const [inspectDoc, setInspectDoc] = useState<ManualDocumentItem | null>(null);
  const [initialUploadFile, setInitialUploadFile] = useState<File | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [inspectingDocId, setInspectingDocId] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>(selectedCategory || 'all');

  const filteredDocs = documents.filter((doc) => {
    if (categoryFilter !== 'all' && doc.category !== categoryFilter) {
      return false;
    }
    return true;
  });

  const handleOpenUpload = (file?: File) => {
    setInitialUploadFile(file || null);
    setUploadModalOpen(true);
  };

  const handleInspectChunks = async (doc: ManualDocumentItem) => {
    setInspectingDocId(doc.id);
    try {
      const reviewed = await workbenchStore.previewDocument(
        doc,
        doc.chunking_profile || 'AUTO'
      );
      setInspectDoc(reviewed);
      setInspectModalOpen(true);
    } catch (err: any) {
      message.error(`無法載入段落品質資料：${err?.message || '伺服器連線異常'}`);
    } finally {
      setInspectingDocId(null);
    }
  };

  const handleDeleteDoc = async (docId: string, title: string) => {
    setDeletingDocId(docId);
    try {
      await workbenchStore.deleteDocument(docId);
      message.success(`已成功刪除手冊《${title}》，並同步自向量索引庫中移除段落！`);
      if (inspectDoc && inspectDoc.id === docId) {
        setInspectModalOpen(false);
        setInspectDoc(null);
      }
    } catch (err: any) {
      const detail = err?.message || '伺服器連線異常';
      message.error(`刪除失敗：${detail}`);
    } finally {
      setDeletingDocId(null);
    }
  };

  const getFileIcon = (fileName: string) => {
    if (fileName.endsWith('.pdf')) return <FilePdfOutlined style={{ color: '#C4314B', fontSize: 18 }} />;
    if (fileName.endsWith('.docx') || fileName.endsWith('.doc'))
      return <FileWordOutlined style={{ color: '#185ABD', fontSize: 18 }} />;
    return <FileTextOutlined style={{ color: '#107C41', fontSize: 18 }} />;
  };

  const columns = [
    {
      title: '手冊名稱與檔案',
      key: 'title',
      render: (_: any, doc: ManualDocumentItem) => (
        <Space direction="vertical" size={2}>
          <Space>
            {getFileIcon(doc.file_name)}
            <Text strong style={{ fontSize: '14px' }}>
              {doc.title}
            </Text>
            <Tag color="blue">{doc.version}</Tag>
          </Space>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            檔案：{doc.file_name} ({((doc.file_size_bytes ?? 0) / 1024 / 1024).toFixed(1)} MB) | 分類：{doc.category}
          </Text>
        </Space>
      ),
    },
    {
      title: '狀態與切分段落',
      key: 'status',
      width: 145,
      render: (_: any, doc: ManualDocumentItem) => {
        const status = DOCUMENT_STATUS[doc.status];
        const inFlight = readFormalPublishInFlight();
        const publishStartedAtMs =
          doc.status === 'PUBLISHING' &&
          inFlight &&
          inFlight.documentId === doc.id
            ? inFlight.startedAtMs
            : null;
        return (
          <Space direction="vertical" size={2}>
            <Tag color={status.color}>{status.label}</Tag>
            {doc.status === 'PUBLISHING' && publishStartedAtMs != null && (
              <Text type="secondary" style={{ fontSize: '11px' }}>
                <PublishElapsedLabel startedAtMs={publishStartedAtMs} />
              </Text>
            )}
            <Text type="secondary" style={{ fontSize: '12px' }}>
              已索引 {doc.chunk_count} 個段落
            </Text>
          </Space>
        );
      },
    },
    {
      title: '最後維護',
      key: 'updated',
      width: 130,
      responsive: ['xxl' as const],
      render: (_: any, doc: ManualDocumentItem) => (
        <Space direction="vertical" size={2}>
          <Text style={{ fontSize: '12px' }}>{doc.updated_at}</Text>
          <Text type="secondary" style={{ fontSize: '11px' }}>
            {doc.updated_by}
          </Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 250,
      render: (_: any, doc: ManualDocumentItem) => (
        <Space size={6} wrap>
          <Tooltip title="預覽段落">
            <Button
              aria-label="預覽段落"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handleInspectChunks(doc)}
              loading={inspectingDocId === doc.id}
            />
          </Tooltip>
          <Tooltip title="在右側測試">
            <Button
              aria-label="在右側測試"
              size="small"
              type="primary"
              ghost
              icon={<PlayCircleOutlined />}
              onClick={() => onTestQuery(`這份 ${doc.title} 寫了什麼重點？`)}
            />
          </Tooltip>
          <DocumentGovernanceActions
            document={doc}
            onComplete={() => {
              if (inspectDoc?.id === doc.id) {
                setInspectModalOpen(false);
                setInspectDoc(null);
              }
            }}
          />
          <Popconfirm
            title="確定要刪除此手冊文件嗎？"
            description={
              <div style={{ maxWidth: 260 }}>
                將刪除《{doc.title}》並同步自向量索引庫中移除所有切分段落，AI 機器人將不再引用此文件。
              </div>
            }
            okText="確認刪除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deletingDocId === doc.id }}
            onConfirm={() => handleDeleteDoc(doc.id, doc.title)}
          >
            <Tooltip title="刪除文件">
              <Button
                aria-label="刪除文件"
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={deletingDocId === doc.id}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* Drag & Drop Upload Zone */}
      <Card size="small" style={{ borderRadius: 10, marginBottom: 16, backgroundColor: '#fcfcfd', border: '1px solid #ebebf2' }}>
        <Dragger
          multiple={false}
          showUploadList={false}
          beforeUpload={(file) => {
            handleOpenUpload(file);
            return false;
          }}
          style={{ padding: '18px 0', border: '2px dashed #d2d3ec', borderRadius: 8, backgroundColor: '#fafafc' }}
        >
          <p className="ant-upload-drag-icon" style={{ marginBottom: 8 }}>
            <InboxOutlined style={{ color: '#5b5fc7', fontSize: 36 }} />
          </p>
          <p className="ant-upload-text" style={{ fontSize: '15px', fontWeight: 'bold', color: '#242424' }}>
            將新版 PDF / Word / MD 操作手冊拖曳至此，或點擊選擇檔案
          </p>
          <p className="ant-upload-hint" style={{ fontSize: '12px', color: '#616161' }}>
            支援 .pdf, .docx, .md 格式 (最大 50MB) · 支援自動封存舊版本，確保 Teams 機器人永遠只引用最新規定！
          </p>
        </Dragger>
      </Card>

      {/* Existing Documents List */}
      <Card
        size="small"
        className="teams-card-hover"
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Text strong style={{ fontSize: '14px' }}>
                文件治理與上線 ({filteredDocs.length})
              </Text>
              <Select
                value={categoryFilter}
                onChange={setCategoryFilter}
                size="small"
                style={{ width: 140 }}
                options={[
                  { label: '全部分類', value: 'all' },
                  { label: '業務交易系統', value: '業務交易系統' },
                  { label: '網路通訊', value: '網路通訊' },
                  { label: '帳號安全', value: '帳號安全' },
                  { label: '通訊協作', value: '通訊協作' },
                  { label: '電子郵件', value: '電子郵件' },
                  { label: 'IT服務指引', value: 'IT服務指引' },
                  { label: '辦公系統', value: '辦公系統' },
                ]}
              />
            </Space>
            <Button
              type="primary"
              size="small"
              icon={<UploadOutlined />}
              onClick={() => handleOpenUpload()}
              style={{ backgroundColor: '#5b5fc7', borderColor: '#5b5fc7' }}
            >
              手動上傳新手冊
            </Button>
          </div>
        }
        style={{ borderRadius: 10 }}
      >
        <Table
          columns={columns}
          dataSource={filteredDocs}
          rowKey="id"
          pagination={false}
          size="middle"
          tableLayout="fixed"
        />
      </Card>

      {/* Upload Modal */}
      <UploadDocumentModal
        open={uploadModalOpen}
        initialFile={initialUploadFile}
        onClose={() => setUploadModalOpen(false)}
        onSuccess={() => {
          workbenchStore.loadDocuments().catch(() => {});
        }}
      />

      {/* Chunk Inspector Modal */}
      <ChunkInspectorModal
        open={inspectModalOpen}
        document={inspectDoc}
        onClose={() => setInspectModalOpen(false)}
        onTestQuery={onTestQuery}
        onDeleteDoc={handleDeleteDoc}
        isDeleting={deletingDocId === inspectDoc?.id}
      />
    </div>
  );
};

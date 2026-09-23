import React, { useEffect, useMemo, useState } from "react";
import {
  Modal,
  Button,
  Space,
  Typography,
  Empty,
  message,
  Popconfirm,
  Alert,
  Pagination,
} from "antd";
import { EyeOutlined, DeleteOutlined } from "@ant-design/icons";
import { ManualDocumentItem } from "../../../shared/api/types";
import { workbenchStore } from "../../../shared/api/workbenchStore";
import { DocumentGovernanceActions } from "./DocumentGovernanceActions";
import { ChunkInspectorChunkCard } from "./ChunkInspectorChunkCard";
import { ChunkInspectorToolbar } from "./ChunkInspectorToolbar";
import {
  ChunkingProfile,
  anomalousChunkIds,
} from "./chunkInspectorUtils";

const { Text } = Typography;

interface ChunkInspectorModalProps {
  open: boolean;
  document: ManualDocumentItem | null;
  onClose: () => void;
  onTestQuery: (query: string) => void;
  onDeleteDoc?: (docId: string, title: string) => Promise<void>;
  isDeleting?: boolean;
  readOnly?: boolean;
}

export const ChunkInspectorModal: React.FC<ChunkInspectorModalProps> = ({
  open,
  document,
  onClose,
  onTestQuery,
  onDeleteDoc,
  isDeleting = false,
  readOnly = false,
}) => {
  const [inspectDoc, setInspectDoc] = useState<ManualDocumentItem | null>(
    document,
  );
  const [expandedChunkIds, setExpandedChunkIds] = useState<Set<string>>(
    new Set(),
  );
  const [chunkSearchText, setChunkSearchText] = useState<string>("");
  const [isRechunking, setIsRechunking] = useState(false);
  const [currentChunkPage, setCurrentChunkPage] = useState(1);
  const [chunkPageSize, setChunkPageSize] = useState(5);
  const hasBlockingChunkIssues = Boolean(
    inspectDoc?.chunks?.some((chunk) =>
      (chunk.quality_issues || []).some(
        (issue) => issue === "HEADING_ONLY" || issue === "DUPLICATE",
      ),
    ),
  );
  const hasShortWarnings = Boolean(
    (inspectDoc?.quality?.shortChunkCount || 0) > 0 ||
      inspectDoc?.chunks?.some((chunk) =>
        (chunk.quality_issues || []).includes("SHORT"),
      ),
  );
  const filteredChunks = useMemo(() => {
    const normalizedSearch = chunkSearchText.trim().toLowerCase();
    return (inspectDoc?.chunks || [])
      .map((chunk, originalIndex) => ({ chunk, originalIndex }))
      .filter(({ chunk }) => {
        if (!normalizedSearch) return true;
        return (
          chunk.title.toLowerCase().includes(normalizedSearch) ||
          chunk.content?.toLowerCase().includes(normalizedSearch) ||
          chunk.content_preview.toLowerCase().includes(normalizedSearch)
        );
      });
  }, [chunkSearchText, inspectDoc?.chunks]);
  const visibleChunks = filteredChunks.slice(
    (currentChunkPage - 1) * chunkPageSize,
    currentChunkPage * chunkPageSize,
  );

  useEffect(() => {
    setInspectDoc(document);
    setExpandedChunkIds(anomalousChunkIds(document));
    setCurrentChunkPage(1);
  }, [document]);

  useEffect(() => {
    const lastPage = Math.max(
      1,
      Math.ceil(filteredChunks.length / chunkPageSize),
    );
    if (currentChunkPage > lastPage) {
      setCurrentChunkPage(lastPage);
    }
  }, [chunkPageSize, currentChunkPage, filteredChunks.length]);

  const handleProfileChange = async (profile: ChunkingProfile) => {
    if (!inspectDoc || readOnly) return;
    setIsRechunking(true);
    try {
      const preview = await workbenchStore.previewDocument(inspectDoc, profile);
      setInspectDoc(preview);
      setExpandedChunkIds(anomalousChunkIds(preview));
      setCurrentChunkPage(1);
      message.success("已重新產生候選段落；正式索引尚未變更。");
    } catch (err: any) {
      message.error(`重新切分失敗：${err?.message || "伺服器連線異常"}`);
    } finally {
      setIsRechunking(false);
    }
  };

  const handleToggleExpandChunk = (chunkId: string) => {
    setExpandedChunkIds((prev) => {
      const next = new Set(prev);
      if (next.has(chunkId)) {
        next.delete(chunkId);
      } else {
        next.add(chunkId);
      }
      return next;
    });
  };

  const handleExpandAllChunks = () => {
    if (!inspectDoc?.chunks) return;
    setExpandedChunkIds(new Set(inspectDoc.chunks.map((c) => c.id)));
  };

  const handleCollapseAllChunks = () => {
    setExpandedChunkIds(new Set());
  };

  return (
    <Modal
      title={
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            width: "100%",
            paddingRight: 24,
          }}
        >
          <Space>
            <EyeOutlined style={{ color: "#5B5FC7", fontSize: 18 }} />
            <Text strong style={{ fontSize: "16px" }}>
              {readOnly
                ? `雲端正式鏡像段落預覽 - ${inspectDoc?.title}`
                : `切分段落檢視器 (Chunk Inspector) - ${inspectDoc?.title}`}
            </Text>
          </Space>
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={[
        !readOnly && inspectDoc && onDeleteDoc ? (
          <Popconfirm
            key="delete-modal"
            title="確定要刪除此手冊文件嗎？"
            description={
              <div style={{ maxWidth: 260 }}>
                將刪除《{inspectDoc.title}
                》並同步自向量索引庫中移除所有切分段落，AI
                機器人將不再引用此文件。
              </div>
            }
            okText="確認刪除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: isDeleting }}
            onConfirm={() => onDeleteDoc(inspectDoc.id, inspectDoc.title)}
          >
            <Button
              danger
              icon={<DeleteOutlined />}
              loading={isDeleting}
              style={{ float: "left" }}
            >
              刪除此手冊
            </Button>
          </Popconfirm>
        ) : null,
        !readOnly && inspectDoc ? (
          <DocumentGovernanceActions
            key="governance-actions"
            document={inspectDoc}
            onComplete={onClose}
          />
        ) : null,
        <Button key="close" onClick={onClose}>
          關閉
        </Button>,
      ]}
      width={840}
      style={{ top: 24 }}
    >
      {inspectDoc?.quality && !readOnly && (
        <Alert
          type={inspectDoc.quality.acceptable ? "success" : "warning"}
          showIcon
          message={
            inspectDoc.quality.acceptable
              ? hasShortWarnings
                ? "可送審：過短段落僅為警告"
                : "候選段落通過 deterministic 品質檢查"
              : "候選段落仍有阻擋送審的品質問題"
          }
          description={`原文覆蓋 ${(inspectDoc.quality.coverageRatio * 100).toFixed(1)}% · 過短 ${inspectDoc.quality.shortChunkCount} · 純標題 ${inspectDoc.quality.headingOnlyCount} · 孤立媒體 ${inspectDoc.quality.orphanMediaCount} · 重複 ${inspectDoc.quality.duplicateChunkCount}${
            inspectDoc.quality.acceptable
              ? hasShortWarnings
                ? "。過短段落已自動合併仍不足時僅標示警告，不阻擋送審。"
                : ""
              : hasBlockingChunkIssues
                ? "。有問題的段落已在下方以橘色框線標示。"
                : "。此問題屬文件層級，請檢查原文覆蓋率或媒體內容。"
          }`}
          style={{ marginBottom: 16 }}
        />
      )}

      {readOnly ? (
        <Alert
          type="info"
          showIcon
          message="這是雲端正式 release 已發布切分，與 Playground Agent 同一份 GCS 鏡像。"
          description="不可重切、刪除或送審。要改內容請在雲端正式工作區發布新 release，再按「立即同步」。"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <ChunkInspectorToolbar
        document={inspectDoc}
        isRechunking={isRechunking}
        chunkSearchText={chunkSearchText}
        readOnly={readOnly}
        onProfileChange={handleProfileChange}
        onSearchChange={(value) => {
          setChunkSearchText(value);
          setCurrentChunkPage(1);
        }}
        onExpandAll={handleExpandAllChunks}
        onCollapseAll={handleCollapseAllChunks}
      />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
          minHeight: 24,
        }}
      >
        <Text strong style={{ color: "#242438" }}>
          段落預覽
        </Text>
        {filteredChunks.length > 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            顯示 {(currentChunkPage - 1) * chunkPageSize + 1}-
            {Math.min(currentChunkPage * chunkPageSize, filteredChunks.length)}
            ，共 {filteredChunks.length} 段
          </Text>
        )}
      </div>

      <div style={{ maxHeight: 520, overflowY: "auto", paddingRight: 4 }}>
        {filteredChunks.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              chunkSearchText
                ? `找不到包含「${chunkSearchText}」的段落`
                : "此手冊尚未解析切分段落"
            }
          />
        ) : (
          visibleChunks.map(({ chunk, originalIndex }) => (
            <ChunkInspectorChunkCard
              key={chunk.id}
              chunk={chunk}
              originalIndex={originalIndex}
              isExpanded={expandedChunkIds.has(chunk.id)}
              documentTitle={inspectDoc?.title}
              onToggleExpand={handleToggleExpandChunk}
              onTestQuery={onTestQuery}
              onClose={onClose}
            />
          ))
        )}
      </div>

      {filteredChunks.length > chunkPageSize && (
        <div
          style={{
            marginTop: 4,
            padding: "14px 16px",
            border: "1px solid #E1E1F0",
            borderRadius: 8,
            backgroundColor: "#F8F8FB",
            display: "flex",
            justifyContent: "center",
          }}
        >
          <Pagination
            current={currentChunkPage}
            pageSize={chunkPageSize}
            total={filteredChunks.length}
            pageSizeOptions={[5, 10, 20]}
            showSizeChanger
            showQuickJumper={filteredChunks.length > chunkPageSize * 4}
            showLessItems
            responsive
            onChange={(page, pageSize) => {
              setCurrentChunkPage(pageSize === chunkPageSize ? page : 1);
              setChunkPageSize(pageSize);
            }}
            showTotal={(total) => `共 ${total} 段`}
          />
        </div>
      )}
    </Modal>
  );
};

import React, { useEffect, useMemo, useState } from "react";
import {
  Modal,
  Button,
  Space,
  Typography,
  Input,
  Tag,
  Card,
  Empty,
  message,
  Popconfirm,
  Alert,
  Select,
  Pagination,
} from "antd";
import {
  EyeOutlined,
  PlayCircleOutlined,
  DownOutlined,
  UpOutlined,
  CopyOutlined,
  SearchOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import {
  ChunkQualityIssue,
  ManualDocumentItem,
} from "../../../shared/api/types";
import { workbenchStore } from "../../../shared/api/workbenchStore";
import { DocumentGovernanceActions } from "./DocumentGovernanceActions";
import { MarkdownChunkContent } from "./MarkdownChunkContent";

const { Text } = Typography;

const QUALITY_ISSUE_LABELS: Record<ChunkQualityIssue, string> = {
  SHORT: "段落過短",
  HEADING_ONLY: "只有標題",
  DUPLICATE: "內容重複",
};

const anomalousChunkIds = (document: ManualDocumentItem | null): Set<string> =>
  new Set(
    (document?.chunks || [])
      .filter(
        (chunk) =>
          Boolean(chunk.quality_issues?.length) ||
          (chunk.token_count || 0) < 80 ||
          (chunk.token_count || 0) > 900,
      )
      .map((chunk) => chunk.id),
  );

interface ChunkInspectorModalProps {
  open: boolean;
  document: ManualDocumentItem | null;
  onClose: () => void;
  onTestQuery: (query: string) => void;
  onDeleteDoc: (docId: string, title: string) => Promise<void>;
  isDeleting?: boolean;
}

export const ChunkInspectorModal: React.FC<ChunkInspectorModalProps> = ({
  open,
  document,
  onClose,
  onTestQuery,
  onDeleteDoc,
  isDeleting = false,
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
  const hasChunkIssues = Boolean(
    inspectDoc?.chunks?.some((chunk) => chunk.quality_issues?.length),
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
    const lastPage = Math.max(1, Math.ceil(filteredChunks.length / chunkPageSize));
    if (currentChunkPage > lastPage) {
      setCurrentChunkPage(lastPage);
    }
  }, [chunkPageSize, currentChunkPage, filteredChunks.length]);

  const handleProfileChange = async (
    profile: "AUTO" | "SLIDE_DECK" | "MANUAL" | "POLICY",
  ) => {
    if (!inspectDoc) return;
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

  const handleCopyChunk = (text: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    message.success("已複製該段落完整內容至剪貼簿！");
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
              切分段落檢視器 (Chunk Inspector) - {inspectDoc?.title}
            </Text>
          </Space>
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={[
        inspectDoc && (
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
        ),
        inspectDoc && (
          <DocumentGovernanceActions
            key="governance-actions"
            document={inspectDoc}
            onComplete={onClose}
          />
        ),
        <Button key="close" onClick={onClose}>
          關閉
        </Button>,
      ]}
      width={840}
      style={{ top: 24 }}
    >
      {inspectDoc?.quality && (
        <Alert
          type={inspectDoc.quality.acceptable ? "success" : "warning"}
          showIcon
          message={
            inspectDoc.quality.acceptable
              ? "候選段落通過 deterministic 品質檢查"
              : "候選段落仍有阻擋發布的品質問題"
          }
          description={`原文覆蓋 ${(inspectDoc.quality.coverageRatio * 100).toFixed(1)}% · 過短 ${inspectDoc.quality.shortChunkCount} · 純標題 ${inspectDoc.quality.headingOnlyCount} · 孤立媒體 ${inspectDoc.quality.orphanMediaCount} · 重複 ${inspectDoc.quality.duplicateChunkCount}${inspectDoc.quality.acceptable ? "" : hasChunkIssues ? "。有問題的段落已在下方以橘色框線標示。" : "。此問題屬文件層級，請檢查原文覆蓋率或媒體內容。"}`}
          style={{ marginBottom: 16 }}
        />
      )}
      {/* Document Info Bar & Actions */}
      <div
        style={{
          padding: "12px 16px",
          backgroundColor: "#F5F5FA",
          border: "1px solid #E1E1F0",
          borderRadius: 8,
          marginBottom: 16,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <Space wrap size="small">
          <Tag color="blue">{inspectDoc?.version}</Tag>
          <Tag color="geekblue">{inspectDoc?.category}</Tag>
          <Text type="secondary" style={{ fontSize: "12px" }}>
            檔案：{inspectDoc?.file_name} · 索引段落總數：
            {inspectDoc?.chunks?.length || 0}
          </Text>
        </Space>

        <Space size="small">
          <Select
            size="small"
            value={inspectDoc?.chunking_profile || "AUTO"}
            loading={isRechunking}
            onChange={handleProfileChange}
            style={{ width: 150 }}
            options={[
              { label: "自動判斷", value: "AUTO" },
              { label: "簡報", value: "SLIDE_DECK" },
              { label: "操作手冊", value: "MANUAL" },
              { label: "政策規章", value: "POLICY" },
            ]}
          />
          <Input
            placeholder="搜尋段落關鍵字..."
            prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
            size="small"
            allowClear
            value={chunkSearchText}
            onChange={(e) => {
              setChunkSearchText(e.target.value);
              setCurrentChunkPage(1);
            }}
            style={{ width: 190 }}
          />
          <Button
            size="small"
            icon={<DownOutlined />}
            onClick={handleExpandAllChunks}
          >
            全部展開
          </Button>
          <Button
            size="small"
            icon={<UpOutlined />}
            onClick={handleCollapseAllChunks}
          >
            全部收合
          </Button>
        </Space>
      </div>

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
          visibleChunks.map(({ chunk, originalIndex }) => {
            const isExpanded = expandedChunkIds.has(chunk.id);
            const fullContent = chunk.content || chunk.content_preview;
            const charCount = chunk.character_count || fullContent.length;
            const qualityIssues = chunk.quality_issues || [];
            const isProblematic = qualityIssues.length > 0;

            return (
              <Card
                key={chunk.id}
                size="small"
                hoverable
                style={{
                  marginBottom: 12,
                  borderRadius: 8,
                  border: isProblematic
                    ? "2px solid #D97706"
                    : isExpanded
                      ? "1px solid #5B5FC7"
                      : "1px solid #E1DFDD",
                  backgroundColor: isProblematic
                    ? "#FFF8E8"
                    : isExpanded
                      ? "#FFFFFF"
                      : "#FAFAFC",
                  transition: "all 0.2s ease",
                }}
              >
                {/* Chunk Header */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 8,
                  }}
                >
                  <Space wrap size="small">
                    <Tag
                      style={{
                        backgroundColor: isExpanded ? "#5B5FC7" : "#F0F1FA",
                        color: isExpanded ? "#FFFFFF" : "#5B5FC7",
                        fontWeight: "bold",
                        borderColor: isExpanded ? "#5B5FC7" : "#D1D3E0",
                      }}
                    >
                      段落 #{originalIndex + 1}
                    </Tag>
                    <Text strong style={{ color: "#242438", fontSize: "14px" }}>
                      {chunk.title}
                    </Text>
                    {chunk.page_number && <Tag>第 {chunk.page_number} 頁</Tag>}
                    {chunk.page_end && chunk.page_end !== chunk.page_number && (
                      <Tag>至第 {chunk.page_end} 頁</Tag>
                    )}
                    {chunk.token_count && (
                      <Tag
                        color={
                          chunk.token_count < 80 || chunk.token_count > 900
                            ? "warning"
                            : "default"
                        }
                      >
                        約 {chunk.token_count} tokens
                      </Tag>
                    )}
                    {chunk.parent_id && (
                      <Tag>Parent {chunk.parent_id.split("-").pop()}</Tag>
                    )}
                    {qualityIssues.map((issue) => (
                      <Tag key={issue} color="warning">
                        {QUALITY_ISSUE_LABELS[issue]}
                      </Tag>
                    ))}
                    <Tag
                      style={{
                        fontSize: "11px",
                        color: "#616161",
                        backgroundColor: "#F3F2F1",
                      }}
                    >
                      {charCount} 字元
                    </Tag>
                  </Space>

                  <Space size="small">
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyChunk(fullContent);
                      }}
                    >
                      複製全文
                    </Button>
                    <Button
                      size="small"
                      type="link"
                      icon={<PlayCircleOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        onTestQuery(
                          `請問 ${inspectDoc?.title} 中提到的「${chunk.title}」詳細內容是什麼？`,
                        );
                        onClose();
                      }}
                      style={{ color: "#5B5FC7", padding: "0 4px" }}
                    >
                      以本段測試
                    </Button>
                    <Button
                      size="small"
                      type={isExpanded ? "primary" : "default"}
                      icon={isExpanded ? <UpOutlined /> : <DownOutlined />}
                      onClick={() => handleToggleExpandChunk(chunk.id)}
                      style={
                        isExpanded
                          ? {
                              backgroundColor: "#5B5FC7",
                              borderColor: "#5B5FC7",
                            }
                          : { borderColor: "#5B5FC7", color: "#5B5FC7" }
                      }
                    >
                      {isExpanded ? "收合全文" : "查看全文"}
                    </Button>
                  </Space>
                </div>

                {/* Chunk Content Preview or Full Detail */}
                {isExpanded ? (
                  <div style={{ marginTop: 10 }}>
                    <div
                      style={{
                        padding: "14px 16px",
                        backgroundColor: "#FCFCFD",
                        border: "1px solid #D2D3EC",
                        borderLeft: "4px solid #5B5FC7",
                        borderRadius: 6,
                        fontSize: "13.5px",
                        lineHeight: 1.75,
                        color: "#242424",
                        wordBreak: "break-word",
                        maxHeight: 380,
                        overflowY: "auto",
                      }}
                    >
                      <MarkdownChunkContent
                        content={fullContent}
                        images={chunk.images}
                      />
                    </div>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginTop: 6,
                        paddingTop: 4,
                      }}
                    >
                      <Text type="secondary" style={{ fontSize: "11px" }}>
                        向量索引依據 · 點擊右側按鈕可收回預覽
                      </Text>
                      <Button
                        type="link"
                        size="small"
                        icon={<UpOutlined />}
                        onClick={() => handleToggleExpandChunk(chunk.id)}
                        style={{ color: "#5B5FC7", fontSize: "12px" }}
                      >
                        收合段落 ▴
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div
                    onClick={() => handleToggleExpandChunk(chunk.id)}
                    style={{
                      marginTop: 8,
                      fontSize: "13px",
                      color: "#616161",
                      lineHeight: 1.6,
                      cursor: "pointer",
                      padding: "6px 10px",
                      borderRadius: 4,
                      backgroundColor: "#F7F7F8",
                    }}
                  >
                    <MarkdownChunkContent
                      content={chunk.content_preview}
                      images={chunk.images}
                      isCompact
                    />
                    <span
                      style={{
                        color: "#5B5FC7",
                        fontWeight: 600,
                        marginLeft: 8,
                        whiteSpace: "nowrap",
                      }}
                    >
                      [點開查看詳細完整內容 ▾]
                    </span>
                  </div>
                )}
              </Card>
            );
          })
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

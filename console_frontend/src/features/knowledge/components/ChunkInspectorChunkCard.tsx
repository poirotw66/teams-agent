import React from "react";
import { Button, Card, Space, Tag, Typography, message } from "antd";
import {
  CopyOutlined,
  DownOutlined,
  PlayCircleOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { ManualChunkItem } from "../../../shared/api/types";
import { MarkdownChunkContent } from "./MarkdownChunkContent";
import { QUALITY_ISSUE_LABELS } from "./chunkInspectorUtils";

const { Text } = Typography;

interface ChunkInspectorChunkCardProps {
  chunk: ManualChunkItem;
  originalIndex: number;
  isExpanded: boolean;
  documentTitle: string | undefined;
  onToggleExpand: (chunkId: string) => void;
  onTestQuery: (query: string) => void;
  onClose: () => void;
}

export const ChunkInspectorChunkCard: React.FC<ChunkInspectorChunkCardProps> = ({
  chunk,
  originalIndex,
  isExpanded,
  documentTitle,
  onToggleExpand,
  onTestQuery,
  onClose,
}) => {
  const fullContent = chunk.content || chunk.content_preview;
  const charCount = chunk.character_count || fullContent.length;
  const qualityIssues = chunk.quality_issues || [];
  const isProblematic = qualityIssues.length > 0;

  const handleCopyChunk = (text: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    message.success("已複製該段落完整內容至剪貼簿！");
  };

  return (
    <Card
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
                `請問 ${documentTitle} 中提到的「${chunk.title}」詳細內容是什麼？`,
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
            onClick={() => onToggleExpand(chunk.id)}
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
              images={chunk.images ?? undefined}
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
              onClick={() => onToggleExpand(chunk.id)}
              style={{ color: "#5B5FC7", fontSize: "12px" }}
            >
              收合段落 ▴
            </Button>
          </div>
        </div>
      ) : (
        <div
          onClick={() => onToggleExpand(chunk.id)}
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
            images={chunk.images ?? undefined}
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
};

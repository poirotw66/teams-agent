import React from "react";
import { Button, Input, Select, Space, Tag, Typography } from "antd";
import {
  DownOutlined,
  SearchOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { ManualDocumentItem } from "../../../shared/api/types";
import { ChunkingProfile } from "./chunkInspectorUtils";

const { Text } = Typography;

interface ChunkInspectorToolbarProps {
  document: ManualDocumentItem | null;
  isRechunking: boolean;
  chunkSearchText: string;
  readOnly?: boolean;
  onProfileChange: (profile: ChunkingProfile) => void;
  onSearchChange: (value: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

export const ChunkInspectorToolbar: React.FC<ChunkInspectorToolbarProps> = ({
  document,
  isRechunking,
  chunkSearchText,
  readOnly = false,
  onProfileChange,
  onSearchChange,
  onExpandAll,
  onCollapseAll,
}) => (
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
      <Tag color="blue">{document?.version}</Tag>
      <Tag color="geekblue">{document?.category}</Tag>
      <Text type="secondary" style={{ fontSize: "12px" }}>
        檔案：{document?.file_name} · 索引段落總數：
        {document?.chunks?.length || 0}
      </Text>
    </Space>

    <Space size="small">
      {readOnly ? (
        <Tag color="geekblue">已發布切分（唯讀）</Tag>
      ) : (
        <Select
          size="small"
          value={document?.chunking_profile || "AUTO"}
          loading={isRechunking}
          onChange={onProfileChange}
          style={{ width: 150 }}
          options={[
            { label: "自動判斷", value: "AUTO" },
            { label: "簡報", value: "SLIDE_DECK" },
            { label: "操作手冊", value: "MANUAL" },
            { label: "政策規章", value: "POLICY" },
          ]}
        />
      )}
      <Input
        placeholder="搜尋段落關鍵字..."
        prefix={<SearchOutlined style={{ color: "#8c8c8c" }} />}
        size="small"
        allowClear
        value={chunkSearchText}
        onChange={(e) => onSearchChange(e.target.value)}
        style={{ width: 190 }}
      />
      <Button size="small" icon={<DownOutlined />} onClick={onExpandAll}>
        全部展開
      </Button>
      <Button size="small" icon={<UpOutlined />} onClick={onCollapseAll}>
        全部收合
      </Button>
    </Space>
  </div>
);

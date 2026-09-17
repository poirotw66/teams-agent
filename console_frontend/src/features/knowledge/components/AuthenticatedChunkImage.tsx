import React, { useCallback, useEffect, useState } from "react";
import { Button, Image, Skeleton, Space, Typography } from "antd";
import {
  FileImageOutlined,
  ReloadOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { ManualChunkImage } from "../../../shared/api/types";
import { authRequestHeaders } from "../../../shared/auth/session";

const { Text } = Typography;

interface AuthenticatedChunkImageProps {
  image: ManualChunkImage;
}

export const AuthenticatedChunkImage: React.FC<
  AuthenticatedChunkImageProps
> = ({ image }) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setError(null);
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!isAllowedAssetUrl(image.url)) {
      setError("圖片路徑未通過安全檢查。");
      return undefined;
    }
    const controller = new AbortController();
    let currentBlobUrl: string | null = null;
    setBlobUrl(null);
    void fetch(image.url, {
      headers: authRequestHeaders(),
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.toLowerCase().startsWith("image/")) {
          throw new Error("伺服器回傳非圖片內容");
        }
        return response.blob();
      })
      .then((blob) => {
        if (controller.signal.aborted) return;
        currentBlobUrl = URL.createObjectURL(blob);
        setBlobUrl(currentBlobUrl);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "圖片載入失敗");
      });
    return () => {
      controller.abort();
      if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
    };
  }, [attempt, image.url]);

  if (error) {
    return (
      <Space
        direction="vertical"
        align="center"
        size={8}
        style={{
          width: "100%",
          padding: 20,
          background: "#FFF8E8",
          borderRadius: 8,
        }}
      >
        <WarningOutlined style={{ color: "#D97706", fontSize: 22 }} />
        <Text type="secondary">
          無法載入「{image.alt_text}」：{error}
        </Text>
        <Button size="small" icon={<ReloadOutlined />} onClick={retry}>
          重試圖片
        </Button>
      </Space>
    );
  }

  if (!blobUrl) {
    return (
      <Space direction="vertical" style={{ width: "100%" }}>
        <Skeleton.Image active />
        <Text type="secondary">
          <FileImageOutlined /> 正在載入索引圖片：{image.alt_text}
        </Text>
      </Space>
    );
  }

  return (
    <figure style={{ margin: "12px 0" }}>
      <Image
        src={blobUrl}
        alt={image.alt_text}
        style={{ maxWidth: "100%", maxHeight: 520, objectFit: "contain" }}
      />
      <figcaption style={{ marginTop: 6, color: "#616161", fontSize: 12 }}>
        {image.alt_text}
      </figcaption>
    </figure>
  );
};

function isAllowedAssetUrl(url: string): boolean {
  if (!url.startsWith("/api/knowledge/v1/documents/")) return false;
  if (
    url.includes("..") ||
    url.includes("\\") ||
    url.includes("?") ||
    url.includes("#")
  ) {
    return false;
  }
  return /\/versions\/[^/]+\/assets\/[^/]+$/.test(url);
}

import React from "react";
import { FileImageOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ManualChunkImage } from "../../../shared/api/types";
import { AuthenticatedChunkImage } from "./AuthenticatedChunkImage";

interface MarkdownChunkContentProps {
  content: string;
  isCompact?: boolean;
  images?: ManualChunkImage[];
}

export const MarkdownChunkContent: React.FC<MarkdownChunkContentProps> = ({
  content,
  isCompact = false,
  images = [],
}) => (
  <div
    style={{
      color: "inherit",
      fontSize: "inherit",
      lineHeight: "inherit",
      overflowWrap: "anywhere",
    }}
  >
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        h1: ({ children }) => (
          <h3
            style={{
              margin: isCompact ? "2px 0" : "0 0 12px",
              fontSize: "1.2em",
            }}
          >
            {children}
          </h3>
        ),
        h2: ({ children }) => (
          <h4
            style={{
              margin: isCompact ? "2px 0" : "14px 0 8px",
              fontSize: "1.1em",
            }}
          >
            {children}
          </h4>
        ),
        h3: ({ children }) => (
          <h5
            style={{
              margin: isCompact ? "2px 0" : "12px 0 6px",
              fontSize: "1em",
            }}
          >
            {children}
          </h5>
        ),
        p: ({ children }) => (
          <p style={{ margin: isCompact ? 0 : "0 0 10px" }}>{children}</p>
        ),
        ul: ({ children }) => (
          <ul style={{ margin: isCompact ? 0 : "0 0 10px", paddingLeft: 24 }}>
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol style={{ margin: isCompact ? 0 : "0 0 10px", paddingLeft: 24 }}>
            {children}
          </ol>
        ),
        blockquote: ({ children }) => (
          <blockquote
            style={{
              margin: "8px 0",
              padding: "6px 12px",
              borderLeft: "3px solid #5B5FC7",
              background: "#F5F5FA",
            }}
          >
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <div style={{ overflowX: "auto", marginBottom: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              {children}
            </table>
          </div>
        ),
        th: ({ children }) => (
          <th
            style={{
              padding: "6px 8px",
              border: "1px solid #D1D3E0",
              background: "#F0F1FA",
              textAlign: "left",
            }}
          >
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td style={{ padding: "6px 8px", border: "1px solid #D1D3E0" }}>
            {children}
          </td>
        ),
        code: ({ children }) => (
          <code
            style={{
              padding: "1px 4px",
              borderRadius: 4,
              background: "#ECECF3",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            {children}
          </code>
        ),
        a: ({ children, href }) => (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
        img: ({ alt, src }) => {
          const image = images.find(
            (candidate) =>
              candidate.path === src ||
              (candidate.path.endsWith(`/${candidate.filename}`) &&
                src?.endsWith(`/${candidate.filename}`)),
          );
          if (!isCompact && image) {
            return <AuthenticatedChunkImage image={image} />;
          }
          return (
            <span
              title={src}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 8px",
                borderRadius: 4,
                background: "#F0F1FA",
                color: "#5B5FC7",
              }}
            >
              <FileImageOutlined />
              {image
                ? `索引圖片：${alt || image.alt_text}`
                : `圖片不可用：${alt || "未命名"}`}
            </span>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  </div>
);

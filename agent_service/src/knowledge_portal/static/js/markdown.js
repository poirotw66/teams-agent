/**
 * High-End Markdown Parser & Document Reader for Knowledge Portal.
 * Parses raw document markdown, extracts archive metadata into clean collapsible sections,
 * and renders formatted, accessible, enterprise-grade typography.
 */

import { loadAssetPreviewUrl } from "./api.js";

export function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sanitizeUrl(url) {
  if (!url) return "";
  const trimmed = String(url).trim();
  if (/^(?:javascript|vbscript):/i.test(trimmed)) return "";
  return trimmed;
}

/**
 * Parses a knowledge document markdown string into structured sections:
 * - Title
 * - Archive metadata (SHA-256, original paths, migration logs)
 * - Limitations / Gaps notes
 * - Canonical instructional content
 */
export function parseDocumentSections(text) {
  let working = (text || "").trim();

  // 1. Strip YAML frontmatter if present
  if (working.startsWith("---")) {
    const endFm = working.indexOf("\n---", 3);
    if (endFm !== -1) {
      working = working.slice(endFm + 4).trim();
    }
  }

  // 2. Extract Document Title from leading # Title
  let docTitle = "";
  const titleMatch = working.match(/^#\s+(.+)$/m);
  if (titleMatch) {
    docTitle = titleMatch[1].trim();
  }

  // 3. Extract ## Archive metadata section
  const archiveMetadata = [];
  const metaHeaderMatch = working.match(/^##\s+Archive\s+metadata\b/im);
  if (metaHeaderMatch) {
    const metaStart = metaHeaderMatch.index;
    const afterMeta = working.slice(metaStart + metaHeaderMatch[0].length);
    const separatorMatch = afterMeta.match(/\n(?:\s*---\s*|\s*##\s+)/);
    const metaEnd = separatorMatch
      ? metaStart + metaHeaderMatch[0].length + separatorMatch.index
      : working.length;
    const metaText = working.slice(metaStart, metaEnd);

    const lineRegex = /^[\s*-]*\*\*([^*]+)\*\*[：:]\s*(.+)$/gm;
    let m;
    while ((m = lineRegex.exec(metaText)) !== null) {
      archiveMetadata.push({
        key: m[1].trim(),
        value: m[2].trim().replace(/^`|`$/g, ""),
      });
    }
    if (archiveMetadata.length === 0) {
      const plainLineRegex = /^[\s*-]+([^：:\n]+)[：:]\s*(.+)$/gm;
      while ((m = plainLineRegex.exec(metaText)) !== null) {
        if (!m[1].toLowerCase().includes("archive metadata")) {
          archiveMetadata.push({
            key: m[1].trim().replace(/^\*\*|\*\*$/g, ""),
            value: m[2].trim().replace(/^`|`$/g, ""),
          });
        }
      }
    }

    const remainderStart = separatorMatch && separatorMatch[0].includes("---")
      ? metaEnd + separatorMatch[0].length
      : metaEnd;
    working = (working.slice(0, metaStart) + "\n" + working.slice(remainderStart)).trim();
  }

  // 4. Extract ## Limitations / Gaps section
  let limitationsText = "";
  const limitsMatch = working.match(/^##\s+(?:Limitations\s*(?:\/\s*Gaps)?|限制與備註)\b/im);
  if (limitsMatch) {
    const limitsStart = limitsMatch.index;
    const afterLimits = working.slice(limitsStart + limitsMatch[0].length);
    const nextHeader = afterLimits.match(/\n(?:\s*##\s+)/);
    const limitsEnd = nextHeader
      ? limitsStart + limitsMatch[0].length + nextHeader.index
      : working.length;
    limitationsText = working.slice(limitsStart + limitsMatch[0].length, limitsEnd).trim();
    working = (working.slice(0, limitsStart) + "\n" + working.slice(limitsEnd)).trim();
  }

  // 5. Clean up redundant headings
  working = working.replace(/^##\s+(?:正文（canonical）|正文\(canonical\)|正文)\s*$/im, "").trim();
  if (docTitle) {
    const escaped = docTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    working = working.replace(new RegExp(`^#\\s+${escaped}\\s*`, "m"), "").trim();
  }

  return {
    docTitle,
    archiveMetadata,
    limitationsText,
    canonicalBody: working,
    raw: text,
  };
}

/**
 * Converts Markdown text into clean, safe, readable HTML.
 */
export function renderMarkdown(md) {
  if (!md || typeof md !== "string") return "";

  // 1. Escape HTML to prevent XSS
  let text = escapeHtml(md);

  // 2. Protect multi-line code blocks
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
    const id = `__CODE_BLOCK_${codeBlocks.length}__`;
    codeBlocks.push({ lang: lang || "text", code });
    return id;
  });

  // 3. Protect inline code
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (match, code) => {
    const id = `__INLINE_CODE_${inlineCodes.length}__`;
    inlineCodes.push(code);
    return id;
  });

  // 4. Blockquotes & Callouts
  text = text.replace(/^(?:&gt;|>)[ ]?(.*)$/gm, (match, content) => {
    const trimmed = content.trim();
    let calloutClass = "doc-quote";
    if (/^(?:注意|警告|Warning|Caution)[：:]/i.test(trimmed)) {
      calloutClass = "doc-quote doc-quote--warning";
    } else if (/^(?:提示|說明|Note|Tip)[：:]/i.test(trimmed)) {
      calloutClass = "doc-quote doc-quote--info";
    }
    return `<blockquote class="${calloutClass}"><p>${content}</p></blockquote>`;
  });
  text = text.replace(/<\/blockquote>\s*<blockquote class="([^"]+)">/g, "<br>");

  // 5. Headings with hierarchy styling
  text = text.replace(/^######\s+(.+)$/gm, '<h6 class="doc-heading doc-h6">$1</h6>');
  text = text.replace(/^#####\s+(.+)$/gm, '<h5 class="doc-heading doc-h5">$1</h5>');
  text = text.replace(/^####\s+(.+)$/gm, '<h4 class="doc-heading doc-h4">$1</h4>');
  text = text.replace(/^###\s+(.+)$/gm, '<h3 class="doc-heading doc-h3">$1</h3>');
  text = text.replace(/^##\s+(.+)$/gm, '<h2 class="doc-heading doc-h2">$1</h2>');
  text = text.replace(/^#\s+(.+)$/gm, '<h1 class="doc-heading doc-h1">$1</h1>');

  // 6. Horizontal Rules
  text = text.replace(/^---(?:\s*---)*$/gm, '<hr class="doc-divider">');

  // 7. Markdown Tables
  text = text.replace(/((?:^\|.+?\|\s*$\n?)+)/gm, (tableText) => {
    const lines = tableText.trim().split("\n").map((l) => l.trim()).filter(Boolean);
    if (lines.length < 2) return tableText;
    const isSep = (line) => /^\|(?:\s*:?-+:?\s*\|)+$/.test(line);
    let headerHtml = "";
    let bodyHtml = "";
    let startIdx = 0;

    if (lines.length >= 2 && isSep(lines[1])) {
      const headers = lines[0].split("|").slice(1, -1).map((c) => c.trim());
      headerHtml = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>`;
      startIdx = 2;
    }
    const bodyRows = [];
    for (let i = startIdx; i < lines.length; i++) {
      if (isSep(lines[i])) continue;
      const cells = lines[i].split("|").slice(1, -1).map((c) => c.trim());
      bodyRows.push(`<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`);
    }
    bodyHtml = `<tbody>${bodyRows.join("")}</tbody>`;
    return `<div class="doc-table-scroll"><table class="doc-table">${headerHtml}${bodyHtml}</table></div>`;
  });

  // 8. Lists (Unordered & Ordered)
  text = text.replace(/^([ \t]*)[-*+][ ]+(.+)$/gm, (match, indent, content) => {
    const isTask = /^\[([ xX])\]\s*(.+)/.exec(content);
    if (isTask) {
      const checked = isTask[1].toLowerCase() === "x" ? "checked" : "";
      return `<ul-task checked="${checked}">${isTask[2]}</ul-task>`;
    }
    return `<ul-item>${content}</ul-item>`;
  });
  text = text.replace(/(<ul-(?:item|task)(?: [^>]+)?>.+?<\/ul-(?:item|task)>\s*)+/g, (listBlock) => {
    const items = listBlock.match(/<ul-(?:item|task)(?: checked="([^"]*)")?>(.+?)<\/ul-(?:item|task)>/g) || [];
    const html = items.map((it) => {
      const taskMatch = /<ul-task checked="([^"]*)">(.+?)<\/ul-task>/.exec(it);
      if (taskMatch) {
        const isChecked = taskMatch[1] === "checked";
        return `<li class="doc-task-item"><input type="checkbox" ${isChecked ? "checked" : ""} disabled> <span>${taskMatch[2]}</span></li>`;
      }
      return it.replace(/<ul-item>(.+?)<\/ul-item>/, "<li>$1</li>");
    }).join("");
    return `<ul class="doc-list">${html}</ul>`;
  });

  text = text.replace(/^([ \t]*)\d+\.[ ]+(.+)$/gm, (match, indent, content) => `<ol-item>${content}</ol-item>`);
  text = text.replace(/(<ol-item>.+?<\/ol-item>\s*)+/g, (listBlock) => {
    const items = listBlock.match(/<ol-item>(.+?)<\/ol-item>/g) || [];
    return `<ol class="doc-ordered-list">${items.map((it) => it.replace(/<ol-item>(.+?)<\/ol-item>/, "<li>$1</li>")).join("")}</ol>`;
  });

  // 9. Images ![alt](url) — local draft assets are hydrated after render
  text = text.replace(/!\[(.*?)\]\((.*?)\)/g, (match, alt, url) => {
    const safeUrl = sanitizeUrl(url);
    const rawUrl = String(url || "").trim();
    const filename = rawUrl.split("/").pop() || alt || "圖片附件";
    const isRemote = /^https?:\/\//i.test(rawUrl) || rawUrl.startsWith("data:");
    const isLocalAsset = !isRemote && Boolean(filename);
    const dataAttr = isLocalAsset
      ? ` data-asset-filename="${escapeHtml(filename)}"`
      : "";
    const initialSrc = isLocalAsset ? "" : safeUrl;
    const onError = isLocalAsset
      ? ""
      : ` onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex';"`;
    return `
      <figure class="doc-figure">
        <img class="doc-img${isLocalAsset ? " doc-img--pending" : ""}" src="${initialSrc}" alt="${escapeHtml(alt || filename)}" loading="lazy"${dataAttr}${onError}>
        <div class="doc-img-fallback"${isLocalAsset ? ' data-asset-fallback="true"' : ""}>
          <span class="img-badge">📷 附件圖片</span>
          <span class="img-name">${escapeHtml(alt || filename)}</span>
          <span class="img-path font-mono">${escapeHtml(url)}</span>
        </div>
        ${alt ? `<figcaption class="doc-figcaption">${escapeHtml(alt)}</figcaption>` : ""}
      </figure>`;
  });

  // 10. Links [text](url)
  text = text.replace(/\[(.*?)\]\((.*?)\)/g, (match, label, url) => {
    const safeUrl = sanitizeUrl(url);
    if (!safeUrl) return label;
    return `<a class="doc-link" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  // 11. Bold, Italic, Strikethrough
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong class="doc-strong">$1</strong>');
  text = text.replace(/__(.+?)__/g, '<strong class="doc-strong">$1</strong>');
  text = text.replace(/\*([^*\n]+)\*/g, '<em class="doc-em">$1</em>');
  text = text.replace(/_([^_\n]+)_/g, '<em class="doc-em">$1</em>');
  text = text.replace(/~~(.+?)~~/g, '<del class="doc-del">$1</del>');

  // 12. Paragraphs & Line Breaks
  const blocks = text.split(/\n\s*\n/);
  text = blocks
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return "";
      if (/^<(h[1-6]|ul|ol|table|blockquote|div|figure|hr)/i.test(trimmed)) {
        return trimmed;
      }
      if (trimmed.startsWith("__CODE_BLOCK_")) {
        return trimmed;
      }
      const withBreaks = trimmed.replace(/\n/g, "<br>");
      return `<p class="doc-p">${withBreaks}</p>`;
    })
    .join("\n");

  // 13. Restore inline code
  text = text.replace(/__INLINE_CODE_(\d+)__/g, (match, idx) => `<code class="doc-inline-code">${inlineCodes[idx]}</code>`);

  // 14. Restore code blocks
  text = text.replace(/__CODE_BLOCK_(\d+)__/g, (match, idx) => {
    const { lang, code } = codeBlocks[idx];
    return `
      <div class="doc-code-card">
        <div class="doc-code-header">
          <span class="doc-code-lang">${lang}</span>
          <button type="button" class="doc-copy-btn" data-copy-code="${encodeURIComponent(code)}">複製</button>
        </div>
        <pre class="doc-code-content"><code>${code}</code></pre>
      </div>`;
  });

  return text;
}

function highlightYamlFrontMatter(raw) {
  return escapeHtml(raw)
    .replace(/^(---)$/gm, '<span class="doc-tok doc-tok--fence">$1</span>')
    .replace(
      /^([A-Za-z_][\w-]*)(:)(\s*)(.*)$/gm,
      '<span class="doc-tok doc-tok--key">$1</span>$2$3<span class="doc-tok doc-tok--val">$4</span>',
    )
    .replace(/^(\s*-\s+)(.+)$/gm, '$1<span class="doc-tok doc-tok--val">$2</span>');
}

function highlightMarkdownSource(raw) {
  return escapeHtml(raw)
    .replace(/^(#{1,6}\s.+)$/gm, '<span class="doc-tok doc-tok--heading">$1</span>')
    .replace(/(!?\[[^\]]*\]\([^)]+\))/g, '<span class="doc-tok doc-tok--link">$1</span>')
    .replace(/(`[^`\n]+`)/g, '<span class="doc-tok doc-tok--code">$1</span>')
    .replace(/^(\s*(?:[-*+]|\d+\.)\s)/gm, '<span class="doc-tok doc-tok--list">$1</span>')
    .replace(/^(&gt;\s.+)$/gm, '<span class="doc-tok doc-tok--quote">$1</span>');
}

function renderRawMarkdownView(content) {
  const text = String(content || "");
  let frontmatter = "";
  let body = text;
  if (text.startsWith("---")) {
    const end = text.indexOf("\n---", 3);
    if (end !== -1) {
      frontmatter = text.slice(0, end + 4);
      body = text.slice(end + 4).replace(/^\r?\n/, "");
    }
  }
  return `
    <div class="doc-raw">
      <textarea class="doc-raw-source" hidden readonly>${escapeHtml(text)}</textarea>
      ${frontmatter
        ? `<section class="doc-raw-block">
            <header class="doc-raw-block__label">Front matter</header>
            <pre class="doc-raw-pre" tabindex="0">${highlightYamlFrontMatter(frontmatter)}</pre>
          </section>`
        : ""}
      <section class="doc-raw-block">
        <header class="doc-raw-block__label">Markdown 正文</header>
        <pre class="doc-raw-pre" tabindex="0">${body ? highlightMarkdownSource(body) : '<span class="doc-tok doc-tok--muted">（空白）</span>'}</pre>
      </section>
    </div>`;
}

/**
 * Renders the full interactive Document Viewer with:
 * - Toolbar (Formatted vs Raw view switcher + Copy button)
 * - Formatted Article View
 * - Extracted Archive Metadata Accordion (Collapsible, unpolluted)
 * - Limitations / Gaps Callout
 * - Raw Markdown View (Collapsible / Toggleable)
 */
export function renderDocumentViewer({
  content = "",
  document: doc = null,
  published = null,
  id = "docViewer",
  compact = false,
}) {
  if (!content) {
    return `<p class="muted">（無內容）</p>`;
  }

  const parsed = parseDocumentSections(content);
  const formattedHtml = renderMarkdown(parsed.canonicalBody);

  const metaCount = parsed.archiveMetadata.length;
  const hasMeta = metaCount > 0;
  const hasLimits = Boolean(parsed.limitationsText);

  const metadataHtml = hasMeta
    ? `
      <details class="doc-archive-accordion">
        <summary>
          <span class="summary-title">
            <span class="summary-icon">📦</span>
            <span>技術歸檔中繼資料 (Archive Metadata)</span>
          </span>
          <span class="summary-badge">${metaCount} 項技術標籤</span>
        </summary>
        <div class="doc-archive-body">
          <dl class="doc-archive-grid">
            ${parsed.archiveMetadata
              .map(
                (item) => `
              <div class="archive-item">
                <dt class="archive-key">${escapeHtml(item.key)}</dt>
                <dd class="archive-val font-mono">${escapeHtml(item.value)}</dd>
              </div>`,
              )
              .join("")}
          </dl>
        </div>
      </details>`
    : "";

  const limitationsHtml = hasLimits
    ? `
      <div class="doc-limitations-box">
        <div class="limitations-header">
          <span class="limitations-icon">⚠️</span>
          <strong>引用限制與路徑備註</strong>
        </div>
        <div class="limitations-content">
          ${renderMarkdown(parsed.limitationsText)}
        </div>
      </div>`
    : "";

  return `
    <div class="doc-viewer ${compact ? "doc-viewer--compact" : ""}" id="${escapeHtml(id)}">
      <div class="doc-viewer-toolbar">
        <div class="doc-mode-toggle" role="group" aria-label="檢視模式">
          <button type="button" class="doc-toggle-btn active" data-mode="formatted" title="排版閱讀模式">
            <span class="btn-icon">📖</span> 排版閱讀
          </button>
          <button type="button" class="doc-toggle-btn" data-mode="raw" title="原始 Markdown">
            <span class="btn-icon">💻</span> 原始 Markdown
          </button>
        </div>
        <div class="doc-toolbar-actions">
          <button type="button" class="btn text doc-copy-action" data-doc-copy title="複製完整內容">
            📋 複製內容
          </button>
        </div>
      </div>

      <div class="doc-viewer-body">
        <div class="doc-view-formatted">
          <article class="doc-article">
            ${formattedHtml}
          </article>
          ${metadataHtml}
          ${limitationsHtml}
        </div>
        <div class="doc-view-raw hidden">
          ${renderRawMarkdownView(content)}
        </div>
      </div>
    </div>`;
}

/**
 * Wires interactivity for all document viewers within the specified root element:
 * - View mode toggling (Formatted vs Raw)
 * - Copy content button
 * - Code snippet copy buttons
 * - Optional hydration of local draft/PDF asset images
 */
export function wireDocumentViewer(root = document, options = {}) {
  if (!root) return;

  // 1. View mode toggle buttons
  root.querySelectorAll(".doc-viewer").forEach((viewer) => {
    const formattedView = viewer.querySelector(".doc-view-formatted");
    const rawView = viewer.querySelector(".doc-view-raw");
    const toggleBtns = viewer.querySelectorAll(".doc-toggle-btn");

    toggleBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.dataset.mode;
        toggleBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        if (mode === "raw") {
          formattedView?.classList.add("hidden");
          rawView?.classList.remove("hidden");
        } else {
          rawView?.classList.add("hidden");
          formattedView?.classList.remove("hidden");
        }
      });
    });

    // 2. Copy whole document button
    const copyBtn = viewer.querySelector("[data-doc-copy]");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const rawSource = viewer.querySelector(".doc-raw-source");
        const rawPre = viewer.querySelector(".content-preview--code");
        const textToCopy = rawSource
          ? rawSource.value
          : (rawPre ? rawPre.textContent : "");
        if (!textToCopy) return;

        try {
          await navigator.clipboard.writeText(textToCopy);
          const origText = copyBtn.innerHTML;
          copyBtn.innerHTML = "✅ 已複製！";
          setTimeout(() => {
            copyBtn.innerHTML = origText;
          }, 2000);
        } catch {
          // Fallback if clipboard API restricted
          const ta = document.createElement("textarea");
          ta.value = textToCopy;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
          const origText = copyBtn.innerHTML;
          copyBtn.innerHTML = "✅ 已複製！";
          setTimeout(() => {
            copyBtn.innerHTML = origText;
          }, 2000);
        }
      });
    }
  });

  // 3. Inline code block copy buttons
  root.querySelectorAll(".doc-copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = decodeURIComponent(btn.dataset.copyCode || "");
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code);
        btn.textContent = "已複製";
        setTimeout(() => {
          btn.textContent = "複製";
        }, 2000);
      } catch {
        btn.textContent = "已複製";
        setTimeout(() => {
          btn.textContent = "複製";
        }, 2000);
      }
    });
  });

  void hydrateDocumentImages(root, options);
}

function base64ToObjectUrl(contentBase64, filename = "image.png") {
  const normalized = String(contentBase64 || "").replace(/^data:[^;]+;base64,/, "");
  const binary = atob(normalized);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  const lower = String(filename).toLowerCase();
  const type = lower.endsWith(".jpg") || lower.endsWith(".jpeg")
    ? "image/jpeg"
    : lower.endsWith(".gif")
      ? "image/gif"
      : lower.endsWith(".webp")
        ? "image/webp"
        : "image/png";
  return URL.createObjectURL(new Blob([bytes], { type }));
}

/**
 * Replace local markdown asset placeholders with real image bytes.
 * Prefer inline base64 (create flow); otherwise fetch draft assets by documentId.
 */
export async function hydrateDocumentImages(root = document, {
  documentId = null,
  inlineAssets = [],
} = {}) {
  if (!root) return;
  const images = [...root.querySelectorAll("img.doc-img[data-asset-filename]")];
  if (!images.length) return;

  const inlineMap = new Map();
  for (const item of inlineAssets || []) {
    const name = item.filename || item.name;
    const b64 = item.content_base64 || item.contentBase64;
    if (name && b64) inlineMap.set(name, b64);
  }

  let resolvePreview = null;
  if (documentId) {
    resolvePreview = loadAssetPreviewUrl;
  }

  await Promise.all(images.map(async (img) => {
    const filename = img.dataset.assetFilename;
    if (!filename) return;
    const fallback = img.parentElement?.querySelector(".doc-img-fallback");
    try {
      let objectUrl = "";
      if (inlineMap.has(filename)) {
        objectUrl = base64ToObjectUrl(inlineMap.get(filename), filename);
      } else if (documentId && resolvePreview) {
        objectUrl = await resolvePreview(documentId, filename);
      } else {
        throw new Error("No asset source");
      }
      img.src = objectUrl;
      img.classList.remove("doc-img--pending");
      img.style.display = "";
      if (fallback) fallback.style.display = "none";
      img.onerror = () => {
        img.style.display = "none";
        if (fallback) fallback.style.display = "flex";
      };
    } catch {
      img.style.display = "none";
      if (fallback) fallback.style.display = "flex";
    }
  }));
}

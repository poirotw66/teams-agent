/**
 * High-End Markdown Parser & Document Reader for Knowledge Portal.
 * Parses raw document markdown, extracts archive metadata into clean collapsible sections,
 * and renders formatted, accessible, enterprise-grade typography.
 */

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

  // 9. Images ![alt](url) with fallback on broken / unhosted assets
  text = text.replace(/!\[(.*?)\]\((.*?)\)/g, (match, alt, url) => {
    const safeUrl = sanitizeUrl(url);
    const filename = (url || "").split("/").pop() || alt || "圖片附件";
    return `
      <figure class="doc-figure">
        <img class="doc-img" src="${safeUrl}" alt="${alt || filename}" loading="lazy" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex';">
        <div class="doc-img-fallback">
          <span class="img-badge">📷 附件圖片</span>
          <span class="img-name">${alt || filename}</span>
          <span class="img-path font-mono">${escapeHtml(url)}</span>
        </div>
        ${alt ? `<figcaption class="doc-figcaption">${alt}</figcaption>` : ""}
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
          <pre class="content-preview content-preview--code font-mono">${escapeHtml(content)}</pre>
        </div>
      </div>
    </div>`;
}

/**
 * Wires interactivity for all document viewers within the specified root element:
 * - View mode toggling (Formatted vs Raw)
 * - Copy content button
 * - Code snippet copy buttons
 */
export function wireDocumentViewer(root = document) {
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
        const rawPre = viewer.querySelector(".content-preview--code");
        const textToCopy = rawPre ? rawPre.textContent : "";
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
}

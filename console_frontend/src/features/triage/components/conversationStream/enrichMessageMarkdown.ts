/** Preprocess bot text to enrich citation markers, normalize headings, unpack steps, and preserve line breaks */
export function enrichMessageMarkdown(content: string): string {
  if (!content) return '';

  let enriched = content.trim();

  // 1. Normalize "問題：" header
  enriched = enriched.replace(
    /(?:^|\n)(?:\*\*)?問題：(?:\*\*)?\s*([^\n]+)/g,
    '\n\n**問題：** $1\n\n'
  );

  // 2. Normalize "處理方式：" header to ensure double newline separation
  enriched = enriched.replace(
    /(?:\n\s*|\A)(?:\*\*)?處理方式：(?:\*\*)?\s*/g,
    '\n\n**處理方式：**\n\n'
  );

  // 3. Normalize "注意事項" / "備註" / "註" callout blockquotes
  enriched = enriched.replace(
    /(?:^|\n)(?:>\s*)?(?:💡\s*)?(?:\*\*)?(?:注意事項|註|備註)[：:]?(?:\*\*)?[ \t]*\n*([\s\S]*?)(?=(?:\n\s*(?:\*\*|來源|問題|處理方式)|\n\n\n|$))/g,
    (_m, body) => {
      const lines = body.trim().split('\n').map((l: string) => l.trim()).filter(Boolean);
      if (lines.length === 0) return '\n\n> 💡 **注意事項**：\n\n';
      if (lines.length === 1) {
        return `\n\n> 💡 **注意事項**：${lines[0].replace(/^[-*]\s*/, '')}\n\n`;
      }
      const quotedLines = lines
        .map((l: string) => `> ${l.startsWith('- ') || l.startsWith('* ') ? l : `- ${l}`}`)
        .join('\n');
      return `\n\n> 💡 **注意事項**：\n>\n${quotedLines}\n\n`;
    }
  );

  // 4. Normalize "來源：" or "來源" header
  enriched = enriched.replace(
    /(?:\n\s*|\A)(?:\*\*)?來源[：:]?(?:\*\*)?\s*(?=\n|$)/g,
    '\n\n**來源**\n\n'
  );

  // 5. Unpack inline numbered steps into true ordered lists
  // 5a. Lead-in sentence into Step 1
  enriched = enriched.replace(
    /(?<!\n)(?:([：:。；;!?！？])\s*|\s+)1\.\s+/g,
    (_m, p1) => (p1 ? `${p1}\n\n1. ` : '\n\n1. ')
  );
  // 5b. Subsequent steps (2., 3., etc.)
  enriched = enriched.replace(
    /(?<!\n)(?:([：:。；;!?！？])\s*|\s+)(\d+)\.\s+/g,
    (_m, p1, p2) => (p1 ? `${p1}\n${p2}. ` : `\n${p2}. `)
  );
  // 5c. Ensure blank line before step 1 if preceded by non-empty line
  enriched = enriched.replace(/([^\n])\n1\.\s+/g, '$1\n\n1. ');

  // 6. Transform source lines like "[S1] Document Title" or "- [S1] Document Title"
  enriched = enriched.replace(
    /(?:^|\n)\s*(?:-\s*)?\[(S\d+|POLICY-SEC-\d{3})\]\s+([^\n\[(]+(?:\([^)]*\)[^\n\[(]*)?)(?=$|\n)/g,
    (_match, tag, title) => {
      const cleanTitle = title.trim();
      return `\n- [${tag}](#citation-${tag}) [${cleanTitle}](#citation-${tag})`;
    }
  );

  // 7. Transform remaining inline markers like [S1] or [POLICY-SEC-001]
  enriched = enriched.replace(
    /(?<!\[)\[(S\d+|POLICY-SEC-\d{3})\](?!\()/g,
    '[$1](#citation-$1)'
  );

  // 8. Convert single newlines in plain paragraphs to hard breaks (2 trailing spaces)
  // so CommonMark preserves intended line breaks instead of collapsing them
  const lines = enriched.split('\n');
  const processedLines = lines.map((line, idx) => {
    if (!line.trim()) return line;
    // Keep list items, blockquotes, tables, and headers as markdown blocks
    if (/^\s*(?:[-*+]|\d+\.|#|>|\|)/.test(line)) return line;
    const nextLine = lines[idx + 1];
    if (
      nextLine === undefined ||
      !nextLine.trim() ||
      /^\s*(?:[-*+]|\d+\.|#|>|\|)/.test(nextLine)
    ) {
      return line;
    }
    return line.endsWith('  ') ? line : `${line}  `;
  });

  return processedLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

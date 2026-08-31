import { escapeHtml } from "./ui.js?v=20260831d";

function lcsTable(before, after) {
  const rows = before.length + 1;
  const cols = after.length + 1;
  const table = Array.from({ length: rows }, () => Array(cols).fill(0));
  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < cols; j += 1) {
      if (before[i - 1] === after[j - 1]) {
        table[i][j] = table[i - 1][j - 1] + 1;
      } else {
        table[i][j] = Math.max(table[i - 1][j], table[i][j - 1]);
      }
    }
  }
  return table;
}

function diffOperations(before, after) {
  const table = lcsTable(before, after);
  const ops = [];
  let i = before.length;
  let j = after.length;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && before[i - 1] === after[j - 1]) {
      ops.unshift({ type: "equal", line: before[i - 1] });
      i -= 1;
      j -= 1;
    } else if (j > 0 && (i === 0 || table[i][j - 1] >= table[i - 1][j])) {
      ops.unshift({ type: "add", line: after[j - 1] });
      j -= 1;
    } else {
      ops.unshift({ type: "remove", line: before[i - 1] });
      i -= 1;
    }
  }
  return ops;
}

export function renderLineDiffHtml(beforeText, afterText) {
  const before = beforeText.split("\n");
  const after = afterText.split("\n");
  const ops = diffOperations(before, after);
  const changed = ops.filter((op) => op.type !== "equal");
  if (!changed.length) {
    return '<p class="muted">內容與正式版本相同。</p>';
  }

  const rows = changed.map((op) => {
    if (op.type === "add") {
      return `<div class="diff-line diff-line-add">+ ${escapeHtml(op.line)}</div>`;
    }
    if (op.type === "remove") {
      return `<div class="diff-line diff-line-del">- ${escapeHtml(op.line)}</div>`;
    }
    return `<div class="diff-line diff-line-equal">${escapeHtml(op.line)}</div>`;
  });
  return `<div class="diff-view">${rows.join("")}</div>`;
}

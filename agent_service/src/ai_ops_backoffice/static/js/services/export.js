import { api, authHeaders, el } from "../api.js";
import { showContentModal } from "../components/modal.js";

export async function pollExport(jobId) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const job = await api(`/api/exports/${encodeURIComponent(jobId)}`);
    if (job.status === "COMPLETED" || job.status === "FAILED" || job.status === "EXPIRED") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return { jobId, status: "RUNNING" };
}

export async function runExport(
  exportFormat,
  exportType = "operations_summary",
  periodOrDays = 7,
  queryFilters = {},
  customReason = "",
) {
  let reason = (customReason || "").trim();
  if (!reason) {
    const input = window.prompt("請輸入匯出原因（至少 3 個字元，將寫入資安稽核紀錄）：", "營運分析與合規稽核");
    if (!input || input.trim().length < 3) {
      if (input !== null) {
        alert("匯出原因必須至少 3 個字元。");
      }
      return null;
    }
    reason = input.trim();
  }

  let days = 7;
  let preset = undefined;
  let startDate = undefined;
  let endDate = undefined;

  if (typeof periodOrDays === "number") {
    days = periodOrDays;
    preset = `${days}d`;
  } else if (typeof periodOrDays === "object" && periodOrDays !== null) {
    preset = periodOrDays.preset;
    days = periodOrDays.days || (
      preset === "today" || preset === "1d" ? 1 :
      preset === "7d" || preset === "1w" ? 7 :
      preset === "180d" || preset === "6m" || preset === "186d" ? 180 :
      preset === "365d" || preset === "1y" || preset === "12m" ? 365 : 30
    );
    startDate = periodOrDays.startDate || periodOrDays.start_date || (
      periodOrDays.start ? `${periodOrDays.start}T00:00:00+08:00` : undefined
    );
    endDate = periodOrDays.endDate || periodOrDays.end_date || (
      periodOrDays.end ? `${periodOrDays.end}T23:59:59+08:00` : undefined
    );
    if (preset === "custom") {
      preset = undefined;
    }
  }

  const payload = {
    export_type: exportType,
    reason,
    days,
    export_format: exportFormat,
    preset: preset || `${days}d`,
    start_date: startDate,
    end_date: endDate,
    ...queryFilters,
  };

  const created = await api("/api/exports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const job = await pollExport(created.jobId);
  if (job.status === "COMPLETED") {
    const response = await fetch(`/api/exports/${encodeURIComponent(created.jobId)}/download`, {
      headers: authHeaders(),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${exportType.replaceAll("_", "-")}-${created.jobId}.${exportFormat}`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return job;
}

export function createExportButton(exportType, periodOrDays, queryFilters = {}) {
  const button = el("button", "", "匯出 CSV");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "匯出中…";
    try {
      const resolvedPeriod = typeof periodOrDays === "function" ? periodOrDays() : periodOrDays;
      const filters = typeof queryFilters === "function" ? queryFilters() : queryFilters;
      await runExport("csv", exportType, resolvedPeriod, filters);
    } catch (error) {
      showContentModal("匯出失敗", el("div", "error", error.message));
    } finally {
      button.disabled = false;
      button.textContent = "匯出 CSV";
    }
  });
  return button;
}

import { api, el } from "../api.js";
import { showContentModal, closeContentModal, showTextPrompt } from "../components/modal.js";
import { faqField, exampleSelect } from "../components/forms.js";
import { actorCapabilities } from "../app/capabilities.js";
import { createPageController } from "../app/lifecycle.js";
import { loadNavFilters } from "../app/navigation.js";
import { navigateReturnTo, parseReturnTo } from "../app/returnTo.js";


async function fetchExampleOptions() {
  const [taxRes, faqRes, docRes] = await Promise.allSettled([
    api("/api/taxonomy"),
    api("/api/faqs"),
    api("/api/knowledge"),
  ]);
  const issueTypes = taxRes.status === "fulfilled" ? (taxRes.value?.items || []) : [];
  const faqs = faqRes.status === "fulfilled" ? (faqRes.value?.items || []) : [];
  const docs = docRes.status === "fulfilled" ? (docRes.value?.items || []) : [];
  return { issueTypes, faqs, docs };
}

function buildExampleForm(record = null, options = {}) {
  const form = el("form", "form-grid");
  if (!record) {
    const sourceSelectWrap = exampleSelect("來源", "source_type", [
      ["MANUAL", "手動建立"], ["FAQ", "FAQ 版本"], ["DOCUMENT", "文件版本"],
    ]);
    const sourceSelect = sourceSelectWrap.querySelector("select");

    const faqOptions = [["", "-- 請選擇來源 FAQ --"]];
    for (const item of (options.faqs || [])) {
      const fObj = item.faq || item;
      const vObj = item.version || {};
      const fid = fObj.faq_id;
      const vid = vObj.version_id || fObj.current_version_id || "v1";
      const title = vObj.content?.question || fObj.title || fid;
      faqOptions.push([`${fid}::${vid}`, `${title} (${fid})`]);
    }
    const faqSelectWrap = exampleSelect("引用既有 FAQ", "faq_picker", faqOptions);
    faqSelectWrap.style.display = "none";

    const docOptions = [["", "-- 請選擇來源文件 --"]];
    for (const item of (options.docs || [])) {
      const did = item.document_id || item.documentId;
      const vid = item.current_version_id || item.version_id || "v1";
      const title = item.title || did;
      docOptions.push([`${did}::${vid}`, `${title} (${did})`]);
    }
    const docSelectWrap = exampleSelect("引用既有文件", "doc_picker", docOptions);
    docSelectWrap.style.display = "none";

    const sourceIdField = faqField("Source ID", "source_id", "", false, false);
    const sourceVersionField = faqField("Source Version ID", "source_version_id", "", false, false);
    const sourceIdInput = sourceIdField.querySelector("input");
    const sourceVersionInput = sourceVersionField.querySelector("input");

    sourceSelect.addEventListener("change", () => {
      const val = sourceSelect.value;
      faqSelectWrap.style.display = val === "FAQ" ? "" : "none";
      docSelectWrap.style.display = val === "DOCUMENT" ? "" : "none";
      if (val === "MANUAL") {
        sourceIdInput.value = "";
        sourceVersionInput.value = "";
      }
    });

    faqSelectWrap.querySelector("select").addEventListener("change", (e) => {
      const val = e.target.value;
      if (val) {
        const [fid, vid] = val.split("::");
        sourceIdInput.value = fid;
        sourceVersionInput.value = vid || "";
      }
    });

    docSelectWrap.querySelector("select").addEventListener("change", (e) => {
      const val = e.target.value;
      if (val) {
        const [did, vid] = val.split("::");
        sourceIdInput.value = did;
        sourceVersionInput.value = vid || "";
      }
    });

    form.append(
      sourceSelectWrap,
      faqSelectWrap,
      docSelectWrap,
      sourceIdField,
      sourceVersionField,
    );
  }

  const issueOptions = [["", "-- 未指定 / 請選擇問題類型 --"]];
  let matchedIssue = false;
  for (const it of (options.issueTypes || [])) {
    const itId = it.issue_type_id || it.id;
    const name = it.display_name || itId;
    issueOptions.push([itId, `${name} (${itId})`]);
    if (record?.expected_issue_type_id === itId) {
      matchedIssue = true;
    }
  }
  if (record?.expected_issue_type_id && !matchedIssue) {
    issueOptions.push([record.expected_issue_type_id, `${record.expected_issue_type_id} (自訂)`]);
  }
  const issueSelectWrap = exampleSelect(
    "Expected Issue Type",
    "expected_issue_type_id",
    issueOptions,
    record?.expected_issue_type_id || "",
  );

  form.append(
    faqField("案例文字", "text", record?.text || "", true),
    issueSelectWrap,
    exampleSelect("Expected Route", "expected_route", [
      ["FAQ", "FAQ"], ["KNOWLEDGE", "KNOWLEDGE"],
      ["TICKET", "TICKET"], ["HANDOFF", "HANDOFF"],
    ], record?.expected_route || "FAQ"),
    exampleSelect("標籤", "label", [
      ["POSITIVE", "正例"], ["NEGATIVE", "反例"],
    ], record?.label || "POSITIVE"),
    faqField("原因（反例必填）", "reason", record?.reason || "", true, false),
  );
  return form;
}

function examplePayload(form) {
  const values = new FormData(form);
  return {
    text: values.get("text"),
    expected_issue_type_id: values.get("expected_issue_type_id") || null,
    expected_route: values.get("expected_route"),
    label: values.get("label"),
    reason: values.get("reason") || null,
  };
}

async function showExampleCreateModal() {
  const options = await fetchExampleOptions();
  const form = buildExampleForm(null, options);
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    const values = new FormData(form);
    const sourceType = values.get("source_type");
    const sourceId = String(values.get("source_id") || "").trim();
    const versionId = String(values.get("source_version_id") || "").trim();
    let path = "/api/examples/manual";
    if (["FAQ", "DOCUMENT", "CONVERSATION"].includes(sourceType)) {
      if (!sourceId || (sourceType !== "CONVERSATION" && !versionId)) {
        message.replaceChildren(el("div", "error", "來源 ID 必填；FAQ/文件來源也需要 Version ID。"));
        submit.disabled = false;
        return;
      }
      if (sourceType === "CONVERSATION") {
        path = `/api/conversations/${encodeURIComponent(sourceId)}/examples`;
      } else {
        const prefix = sourceType === "FAQ" ? "/api/faqs" : "/api/knowledge";
        path = `${prefix}/${encodeURIComponent(sourceId)}/versions/${encodeURIComponent(versionId)}/examples`;
      }
    }
    try {
      const created = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(examplePayload(form)),
      });
      closeContentModal();
      await renderExamples();
      await showExampleDetail(created.example.example_id);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("新增品質案例", form);
}

async function showExampleEditModal(record) {
  const options = await fetchExampleOptions();
  const form = buildExampleForm(record, options);
  const message = el("div");
  const submit = el("button", "", "儲存為草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await api(`/api/examples/${encodeURIComponent(record.example_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...examplePayload(form), expected_etag: record.etag }),
      });
      await renderExamples();
      await showExampleDetail(record.example_id);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("編輯品質案例", form);
}

async function showExampleDetail(exampleId) {
  try {
    const detail = await api(`/api/examples/${encodeURIComponent(exampleId)}`);
    const record = detail.example;
    const allowed = actorCapabilities();
    const content = el("div");
    content.append(
      el("p", "", `${record.status}｜${record.source_type}:${record.source_id}｜ETag ${record.etag}`),
      el("p", "", record.text),
      el("p", "", `Expected：${record.expected_issue_type_id} → ${record.expected_route}`),
      el("p", "", `標籤：${record.label}｜Owner：${record.owner_unit_id}`),
    );
    if (record.reason) content.append(el("p", "", `原因：${record.reason}`));
    if (record.dataset_version) content.append(el("p", "", `Dataset：${record.dataset_version}`));
    const actions = el("div", "filter-bar");
    const run = async (path, payload) => {
      try {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        });
        await renderExamples();
        await showExampleDetail(exampleId);
      } catch (error) {
        showContentModal("案例操作失敗", el("div", "error", error.message));
      }
    };
    if (allowed.has("ops.examples.write") && record.status !== "RETIRED") {
      const edit = el("button", "", "編輯");
      edit.addEventListener("click", () => showExampleEditModal(record));
      actions.append(edit);
    }
    if (allowed.has("ops.examples.verify") && ["DRAFT", "REJECTED"].includes(record.status)) {
      const verify = el("button", "", "驗證通過");
      verify.addEventListener("click", () => run(`/api/examples/${exampleId}/review`, {
        expected_etag: record.etag, approve: true, reason: "SYSTEM_ADMIN 已驗證標籤與預期結果",
      }));
      const reject = el("button", "", "拒絕");
      reject.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "拒絕品質案例",
          message: "請輸入拒絕原因。",
          required: true,
        });
        if (reason?.trim()) run(`/api/examples/${exampleId}/review`, {
          expected_etag: record.etag, approve: false, reason: reason.trim(),
        });
      });
      actions.append(verify, reject);
    }
    if (allowed.has("ops.examples.retire") && record.status !== "RETIRED") {
      const retire = el("button", "", "退役");
      retire.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "退役品質案例",
          message: "請輸入退役原因。",
          required: true,
        });
        if (reason?.trim()) run(`/api/examples/${exampleId}/retire`, {
          expected_etag: record.etag, reason: reason.trim(),
        });
      });
      actions.append(retire);
    }
    content.append(actions, el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(`品質案例 ${record.example_id}`, content);
  } catch (error) {
    showContentModal("品質案例", el("div", "error", error.message));
  }
}

export async function renderExamples() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  const allowed = actorCapabilities();
  const nav = loadNavFilters();
  if (parseReturnTo(nav.returnTo)) {
    const back = el("button", "button-link", "← 返回改善案件");
    back.type = "button";
    back.addEventListener("click", () => navigateReturnTo("workHub", {}));
    panel.append(back);
  }
  const actions = el("div", "filter-bar");
  const sourceType = el("select");
  sourceType.innerHTML = `
    <option value="">全部來源</option><option value="FAQ">FAQ</option>
    <option value="DOCUMENT">DOCUMENT</option><option value="CONVERSATION">CONVERSATION</option>
    <option value="MANUAL">MANUAL</option>`;
  const status = el("select");
  status.innerHTML = `
    <option value="">全部狀態</option><option value="DRAFT">DRAFT</option>
    <option value="VERIFIED">VERIFIED</option><option value="REJECTED">REJECTED</option>
    <option value="RETIRED">RETIRED</option>`;
  const sourceId = el("input");
  sourceId.placeholder = "Source ID";
  const apply = el("button", "", "套用篩選");
  const result = el("div");
  const summary = el("span", "metric-label");
  const load = async () => {
    try {
      const params = new URLSearchParams();
      if (sourceType.value) params.set("source_type", sourceType.value);
      if (status.value) params.set("status", status.value);
      if (sourceId.value.trim()) params.set("source_id", sourceId.value.trim());
      const data = await api(`/api/examples?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的品質案例。"));
        return;
      }
      const table = el("table");
      table.innerHTML = "<thead><tr><th>案例</th><th>來源</th><th>預期</th><th>狀態</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const action = el("td");
        const detail = el("button", "", "查看與處理");
        detail.addEventListener("click", () => showExampleDetail(item.example_id));
        action.append(detail);
        const row = el("tr");
        row.append(
          el("td", "", item.text),
          el("td", "", `${item.source_type}:${item.source_id}`),
          el("td", "", `${item.expected_issue_type_id} → ${item.expected_route}`),
          el("td", "", item.status),
          action,
        );
        body.append(row);
      }
      table.append(body);
      const examplesScroll = el("div", "table-responsive");
      examplesScroll.append(table);
      result.append(examplesScroll);
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  };
  apply.addEventListener("click", load);
  if (allowed.has("ops.examples.write")) {
    const create = el("button", "", "新增案例");
    create.addEventListener("click", showExampleCreateModal);
    actions.append(create);
  }
  actions.append(sourceType, status, sourceId, apply, summary);
  panel.append(el("h2", "", "品質案例集"), actions, result);
  app.replaceChildren(panel);
  await load();
}

export const examplesPage = createPageController({
  enter: async () => renderExamples(),
  update: async () => renderExamples(),
  leave: async () => {},
});

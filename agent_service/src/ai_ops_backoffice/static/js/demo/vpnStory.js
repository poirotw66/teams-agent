/**
 * Fixed first-demo story. Prepared ahead of the walkthrough.
 * Nothing here writes live policy, publishes, or pretends an eval just ran.
 */

import { el } from "../api.js";
import { navigateTo } from "../app/navigation.js";
import { withReturnTo } from "../app/returnTo.js";

export const VPN_DEMO_CASE_ID = "demo-vpn-incomplete";
export const VPN_DEMO_CONVERSATION_ID = VPN_DEMO_CASE_ID;

export const VPN_STORY = {
  caseId: VPN_DEMO_CASE_ID,
  problem: "VPN 回答不完整",
  reason: "員工問申請方式，回答只寫重新連線，沒有申請資格和入口。",
  owner: "資訊客服",
  nextStep: "開啟《VPN 常見問答》，補上申請資格。",
  question: "請問 VPN 要怎麼申請？",
  answer:
    "VPN 連不上時，請先確認網路與帳號權限，再重新連線。若仍失敗，請聯繫資訊小幫手。",
  sourceExcerpt: "連線異常：請確認網路與帳號權限後重新連線。",
  feedbackReason: "這題是在問怎麼申請，不是連不上。回答沒有申請資格，也沒有申請入口。",
  documentTitle: "VPN 常見問答",
  publishedVersion: "目前員工看到的版本",
  documentVersion: "示範修訂",
  reviewStatus: "待審核",
  reviewer: "內容負責人",
  missing: "申請資格，以及要去哪裡送出申請。",
  added: "正職員工可向直屬主管申請。申請入口是資訊服務台的 VPN 申請表。",
  basis: "VPN 常見問答，示範修訂，尚未發布",
  preparedNote: "這組比較是事先準備的驗收結果，不是剛剛現場執行。",
  conversationNote:
    "這是事先對好的示範對話。現場若改用 Teams 問同一題，請對照這一則，不要把它說成剛剛問出來的。",
};

export function isVpnDemoCase(caseId) {
  return String(caseId || "") === VPN_DEMO_CASE_ID;
}

function actionButton(label, onClick, primary = false) {
  const button = el("button", primary ? "button-primary" : "", label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

function openDocument() {
  navigateTo(
    "contentLists",
    withReturnTo(
      { demoDoc: "vpn", tab: "documents" },
      "workHub",
      { story: "case" },
    ),
  );
}

function openCase() {
  navigateTo("workHub", { story: "case" });
}

function openComparison() {
  navigateTo("workHub", { story: "compare" });
}

export function openVpnConversation() {
  navigateTo("conversations", { conversationId: VPN_DEMO_CONVERSATION_ID });
}

export function isVpnDemoConversation(conversationId) {
  return String(conversationId || "") === VPN_DEMO_CONVERSATION_ID;
}

export function vpnWorkItems() {
  return {
    seen: {
      problem: VPN_STORY.question,
      reason: "回答有附上文件，但內容只寫重新連線。",
      owner: VPN_STORY.owner,
      nextStep: "開啟這則回答，點開文件名稱與版本。",
      actionLabel: "查看這則回答",
      open: openVpnConversation,
    },
    mine: {
      problem: VPN_STORY.problem,
      reason: VPN_STORY.reason,
      owner: VPN_STORY.owner,
      nextStep: VPN_STORY.nextStep,
      actionLabel: "查看這筆負評",
      open: openCase,
    },
    review: {
      problem: VPN_STORY.documentTitle,
      reason: "示範修訂已寫好，還沒有人確認。",
      owner: VPN_STORY.reviewer,
      nextStep: "打開修改差異，確認補上的是申請資格。",
      actionLabel: "開啟修改差異",
      open: openDocument,
    },
    done: {
      problem: "VPN 申請資格說明已補齊",
      reason: "事先準備的比較顯示缺漏已補上，且其他題沒有變差。",
      owner: VPN_STORY.owner,
      nextStep: "查看改善前後回答，再決定是否發布。",
      actionLabel: "看改善前後",
      open: openComparison,
    },
  };
}

function storyHeader(title, lead) {
  const header = el("div", "bu-page-header");
  header.append(el("h2", "", title), el("p", "ov-lead", lead));
  return header;
}

function fact(label, value) {
  const row = el("div", "demo-fact");
  row.append(el("span", "demo-fact-label", label), el("p", "", value));
  return row;
}

export function renderVpnConversation(app) {
  const page = el("section", "demo-story");
  page.append(
    storyHeader("員工看到的回答", VPN_STORY.conversationNote),
  );
  const panel = el("section", "ov-panel");
  panel.append(
    fact("員工問題", VPN_STORY.question),
    fact("AI 回答", VPN_STORY.answer),
    fact("來源文件", VPN_STORY.documentTitle),
    fact("來源版本", VPN_STORY.publishedVersion),
    fact("點開後會看到", VPN_STORY.sourceExcerpt),
  );
  const actions = el("div", "demo-actions");
  actions.append(actionButton("開啟文件與版本", openDocument, true));
  const more = el("details", "ops-more");
  more.append(el("summary", "", "更多操作"));
  more.append(actionButton("看這筆負評", openCase));
  panel.append(actions, more);
  page.append(panel);
  app.replaceChildren(page);
}

export function renderVpnCase(app) {
  const page = el("section", "demo-story");
  page.append(
    storyHeader(
      VPN_STORY.problem,
      "先看員工問了什麼、當時答了什麼、為什麼被評負評。",
    ),
  );
  const panel = el("section", "ov-panel");
  panel.append(
    fact("員工問題", VPN_STORY.question),
    fact("當時回答", VPN_STORY.answer),
    fact("依據", "VPN 常見問答裡的連線異常段落。這份文件沒有寫申請方式。"),
    fact("負評原因", VPN_STORY.feedbackReason),
    fact("負責人", VPN_STORY.owner),
    fact("下一步", VPN_STORY.nextStep),
  );
  const actions = el("div", "demo-actions");
  actions.append(actionButton("修正文件", openDocument, true));
  const more = el("details", "ops-more");
  more.append(el("summary", "", "更多操作"));
  const moreActions = el("div", "demo-actions");
  moreActions.append(
    actionButton("看改善前後", openComparison),
    actionButton("返回待處理問題", () => navigateTo("workHub")),
  );
  more.append(moreActions);
  panel.append(actions, more);
  page.append(panel);
  app.replaceChildren(page);
}

export function renderVpnDocument(app) {
  const page = el("section", "demo-story");
  page.append(
    storyHeader(
      VPN_STORY.documentTitle,
      "這是事先寫好的示範修訂，不會寫入目前生效的政策。",
    ),
  );
  const panel = el("section", "ov-panel");
  panel.append(
    fact("目前版本", VPN_STORY.publishedVersion),
    fact("這次版本", VPN_STORY.documentVersion),
    fact("審核狀態", VPN_STORY.reviewStatus),
    fact("誰負責確認", VPN_STORY.reviewer),
    el("h3", "ov-panel-title", "原本寫的"),
    el("p", "demo-copy", VPN_STORY.sourceExcerpt),
    el("h3", "ov-panel-title", "這次補上的"),
    el("p", "demo-copy", VPN_STORY.added),
    el(
      "p",
      "ov-lead",
      "下一步是請內容負責人看過差異。下面這個動作不會送出，也不會改到目前生效的版本。",
    ),
  );
  const confirm = actionButton("請內容負責人確認", () => {});
  confirm.disabled = true;
  confirm.title = "示範修訂不會送出審核";
  const actions = el("div", "demo-actions");
  actions.append(confirm);
  const more = el("details", "ops-more");
  more.append(el("summary", "", "更多操作"));
  more.append(actionButton("返回這筆案件", openCase));
  panel.append(actions, more);
  page.append(panel);
  app.replaceChildren(page);
}

export function renderVpnComparison(app) {
  const page = el("section", "demo-story");
  page.append(
    storyHeader("改善前後", VPN_STORY.preparedNote),
  );
  const panel = el("section", "ov-panel");
  panel.append(
    fact("原本漏了什麼", VPN_STORY.missing),
    fact("現在補了什麼", VPN_STORY.added),
    fact("依據是哪份文件", VPN_STORY.basis),
    fact("其他回答", "同一份比較裡，連線失敗和帳號鎖定兩題沒有變差。"),
    fact("後續發布", "已事先放到待發布。確認後才會換成員工看到的版本。"),
    fact("後續追蹤", "發布後回來看同一題還會不會再被評負評。這一步也還沒有在現場執行。"),
  );
  const actions = el("div", "demo-actions");
  actions.append(actionButton("回到待處理問題", () => navigateTo("workHub"), true));
  const more = el("details", "ops-more");
  more.append(el("summary", "", "更多操作"));
  more.append(actionButton("返回這筆案件", openCase));
  panel.append(actions, more);
  page.append(panel);
  app.replaceChildren(page);
}

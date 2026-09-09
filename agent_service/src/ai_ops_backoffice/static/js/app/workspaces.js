/** Workspace catalog for the AI Ops backoffice shell. */

export const WORKSPACE_KEY = "ai_ops_active_workspace";
export const NAV_FILTERS_KEY = "ai_ops_nav_filters";

export const workspaces = [
  {
    id: "knowledge_ops",
    label: "知識營運",
    hint: "固定答案 FAQ 與知識文件分開維護；可手動關聯，不會自動互抄內文",
    items: [
      ["contentHub", "內容維護", "content.hub"],
      ["quality", "品質案件", "ops.feedback.read"],
      ["knowledgeWork", "文件待辦", "knowledge.ui"],
      ["knowledgePortal", "知識文件庫", "knowledge.ui"],
      ["faq", "FAQ 管理", "ops.faq.read"],
      ["knowledgeReviews", "待審清單", "knowledge.review.ui"],
      ["knowledgeReleases", "發布紀錄", "knowledge.ui"],
      ["knowledge", "內容成效", "ops.knowledge.read"],
      ["sync", "同步工作", "ops.sync.read"],
      ["knowledgeAudit", "知識稽核", "knowledge.ui"],
      ["evaluations", "品質驗收", "ops.evals.read"],
      ["examples", "案例集驗證", "ops.examples.read"],
      ["conversations", "回答驗證", "ops.conversations.read"],
    ],
  },
  {
    id: "ai_ops",
    label: "AI 管理",
    hint: "資料集、評測、Prompt、模型與發布",
    items: [
      ["evaluations", "品質驗收", "ops.evals.read"],
      ["examples", "資料集／案例", "ops.examples.read"],
      ["prompts", "Prompt 與評測", "ops.prompts.read"],
      ["models", "模型設定", "ops.models.read"],
      ["flags", "Feature Flag", "ops.flags.read"],
    ],
  },
  {
    id: "platform",
    label: "平台管理",
    hint: "權限、背景工作、稽核、保存與告警",
    items: [
      ["overview", "營運總覽", "ops.summary.read"],
      ["issues", "Issue 分析", "ops.issues.read"],
      ["routes", "路由來源", "ops.issues.read"],
      ["costs", "成本分析", "ops.cost.read"],
      ["budgets", "預算與告警", "ops.budget.read"],
      ["health", "系統健康度", "ops.health.read"],
      ["roles", "權限／角色", "ops.roles.read"],
      ["retention", "保存政策", "ops.retention.read"],
      ["masking", "遮罩政策", "ops.retention.read"],
      ["search", "全域搜尋", "ops.search.read"],
      ["audit", "稽核紀錄", "ops.audit.read"],
    ],
  },
];

export const ROLE_DEFAULT_WORKSPACE = {
  KNOWLEDGE_ADMIN: "knowledge_ops",
  SERVICE_OWNER: "knowledge_ops",
  AI_ADMIN: "ai_ops",
  SYSTEM_ADMIN: "platform",
  ANALYST: "platform",
  AUDITOR: "platform",
};

export const VIEW_TITLES = Object.fromEntries(
  workspaces.flatMap((workspace) =>
    workspace.items.map(([id, label]) => [id, label]),
  ),
);

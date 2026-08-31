import { confirmDialog } from "./ui.js?v=20260831d";

export async function handleConflictError(error, refresh) {
  if (error?.status !== 409 && error?.code !== "CONFLICT") {
    return false;
  }
  const ok = await confirmDialog(
    "版本衝突",
    error.message || "這份文件剛被其他人更新過。請重新載入最新內容後再試一次。",
    { confirmLabel: "重新載入" },
  );
  if (ok && refresh) {
    await refresh();
  }
  return true;
}

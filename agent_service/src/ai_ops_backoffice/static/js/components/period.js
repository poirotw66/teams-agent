import { el } from "../api.js";

export function periodSelect(current = "7d") {
  const select = el("select", "");
  select.innerHTML = `
    <option value="today">今天</option>
    <option value="1d">最近 1 日</option>
    <option value="7d">最近 1 週</option>
    <option value="30d">最近 1 個月</option>
    <option value="month">本月</option>
    <option value="6m">最近 6 個月</option>
    <option value="1y">最近 1 年</option>
    <option value="custom">自訂期間</option>
  `;
  select.value = current;
  return select;
}

export function intervalSelect(current = "DAY") {
  const select = el("select", "");
  select.innerHTML = `
    <option value="DAY">依日</option>
    <option value="WEEK">依週</option>
    <option value="MONTH">依月</option>
  `;
  select.value = ["DAY", "WEEK", "MONTH"].includes(current) ? current : "DAY";
  select.setAttribute("aria-label", "趨勢粒度");
  return select;
}

export function formatLocalClock(isoValue, timeZone = "Asia/Taipei") {
  if (!isoValue) return "-";
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString("zh-TW", {
    timeZone,
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function customPeriodInputs(startValue = "", endValue = "") {
  const wrap = el("div", "filter-bar");
  const start = el("input");
  start.type = "date";
  start.id = "custom-start-date";
  start.value = startValue;
  const end = el("input");
  end.type = "date";
  end.id = "custom-end-date";
  end.value = endValue;
  wrap.append(el("label", "", "開始"), start, el("label", "", "結束"), end);
  return wrap;
}

export function periodParams(state = { preset: "30d" }) {
  const params = new URLSearchParams();
  if (state.preset === "custom") {
    if (state.start) params.set("start_date", `${state.start}T00:00:00+08:00`);
    if (state.end) params.set("end_date", `${state.end}T23:59:59+08:00`);
  } else {
    params.set("preset", state.preset || "30d");
  }
  return params;
}

export function buildPeriodQuery(prefix = "", period = null, fallbackPreset = "7d") {
  if (period) {
    return periodParams(period).toString();
  }
  const presetEl = document.getElementById(`${prefix}overview-preset`);
  const preset = presetEl?.value || fallbackPreset || "7d";
  if (preset === "custom") {
    const start = document.getElementById(`${prefix}custom-start-date`)?.value;
    const end = document.getElementById(`${prefix}custom-end-date`)?.value;
    return periodParams({ preset, start, end }).toString();
  }
  return periodParams({ preset }).toString();
}

export function createPeriodControls(state, onApply) {
  const controls = el("div", "filter-bar");
  const select = periodSelect(state.preset || "30d");
  select.setAttribute("aria-label", "分析期間");
  const custom = customPeriodInputs(state.start || "", state.end || "");
  custom.hidden = select.value !== "custom";
  select.addEventListener("change", () => {
    custom.hidden = select.value !== "custom";
  });
  const apply = el("button", "", "套用期間");
  apply.addEventListener("click", () => {
    const inputs = custom.querySelectorAll("input");
    onApply({
      preset: select.value,
      start: inputs[0]?.value || "",
      end: inputs[1]?.value || "",
    });
  });
  controls.append(select, custom, apply);
  return controls;
}

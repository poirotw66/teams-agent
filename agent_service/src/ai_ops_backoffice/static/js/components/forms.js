import { el } from "../api.js";

export function faqField(label, name, value = "", multiline = false, required = true) {
  const wrap = el("label", "form-field");
  wrap.append(el("span", "metric-label", label));
  const input = el(multiline ? "textarea" : "input");
  input.name = name;
  input.value = value;
  input.required = required;
  wrap.append(input);
  return wrap;
}

export function exampleSelect(label, name, options, value = "") {
  const wrap = el("label", "form-field");
  wrap.append(el("span", "metric-label", label));
  const select = el("select");
  select.name = name;
  for (const [optionValue, optionLabel] of options) {
    const option = el("option", "", optionLabel);
    option.value = optionValue;
    select.append(option);
  }
  select.value = value;
  wrap.append(select);
  return wrap;
}

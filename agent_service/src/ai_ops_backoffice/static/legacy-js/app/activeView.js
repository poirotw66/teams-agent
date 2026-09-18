/** Currently active backoffice view id (hash/nav). */

let currentActiveView = "overview";

export function getCurrentActiveView() {
  return currentActiveView;
}

export function setCurrentActiveView(view) {
  currentActiveView = view;
}

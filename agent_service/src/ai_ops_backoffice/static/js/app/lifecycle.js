/**
 * Page lifecycle controller for backoffice views.
 * Each view should expose enter/update/leave so routing can clean up timers
 * and listeners without knowing page internals.
 */

let activePage = null;

export function getActivePage() {
  return activePage;
}

export async function enterPage(page, context = {}) {
  if (activePage && typeof activePage.leave === "function") {
    await activePage.leave();
  }
  activePage = page;
  if (page && typeof page.enter === "function") {
    await page.enter(context);
  }
}

export async function updateActivePage(context = {}) {
  if (activePage && typeof activePage.update === "function") {
    await activePage.update(context);
  }
}

export async function leaveActivePage() {
  if (activePage && typeof activePage.leave === "function") {
    await activePage.leave();
  }
  activePage = null;
}

export function createPageController({ enter, update, leave } = {}) {
  return {
    enter: enter || (async () => {}),
    update: update || (async () => {}),
    leave: leave || (async () => {}),
  };
}

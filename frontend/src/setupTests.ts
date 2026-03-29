import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrollIntoView — stub it globally so components that
// call element.scrollIntoView() don't crash in the test environment.
window.HTMLElement.prototype.scrollIntoView = function () {};

import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrollIntoView — stub it globally so components that
// call element.scrollIntoView() don't crash in the test environment.
window.HTMLElement.prototype.scrollIntoView = function () {};

// jsdom also does not implement element.scrollTo — stub it so components that
// call el.scrollTo({ top: … }) don't throw in the test environment.
window.HTMLElement.prototype.scrollTo = function () {};

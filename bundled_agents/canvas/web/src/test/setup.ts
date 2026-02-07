import '@testing-library/jest-dom/vitest'

// Mock URL.createObjectURL / revokeObjectURL (not available in jsdom)
if (typeof URL.createObjectURL === 'undefined') {
  URL.createObjectURL = () => 'blob:mock-url'
  URL.revokeObjectURL = () => {}
}

// Mock ResizeObserver (not available in jsdom)
if (typeof ResizeObserver === 'undefined') {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

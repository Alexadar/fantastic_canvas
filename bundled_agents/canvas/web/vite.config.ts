/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: {
    alias: {
      '@bundles': path.resolve(__dirname, '../..'),  // → bundled_agents/
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/ws': {
        target: 'ws://127.0.0.1:8888',
        ws: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8888',
      },
      '/content': {
        target: 'http://127.0.0.1:8888',
      },
      '/bundles': {
        target: 'http://127.0.0.1:8888',
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})

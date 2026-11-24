import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost/',
      },
    },
    exclude: ['node_modules/**', 'dist/**', 'tests/e2e/**'],
    setupFiles: './tests/frontend/setup.ts',
    globals: true,
  },
})

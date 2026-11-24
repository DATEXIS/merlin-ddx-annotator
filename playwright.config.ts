import { defineConfig, devices } from '@playwright/test'

// End-to-end tests run against the real demo server (study backend + built frontend)
// on a fresh copy of the synthetic data. Build first: `npm run build`.
const python = process.env.PYTHON ?? 'python'
const port = 8766

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `${python} scripts/run_demo.py --reset --port ${port} --data-root .demo/e2e_data_root`,
    url: `http://127.0.0.1:${port}/healthz`,
    reuseExistingServer: false,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})

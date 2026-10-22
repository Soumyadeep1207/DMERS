import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
    coverage: {
      provider: 'v8',
      include: ['src/modules/ai/**/*.js'],
      reporter: ['text', 'json-summary'],
      thresholds: { statements: 90 },
    },
  },
});

import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    exclude: [...configDefaults.exclude, 'browser-tests/**'],
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
    server: {
      deps: {
        inline: ['@uiw/react-md-editor', '@uiw/react-markdown-preview'],
      },
    },
  },
});

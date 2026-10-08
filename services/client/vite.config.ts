import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.DEV_FRONTEND_PORT || 4321),
    host: '127.0.0.1',
    proxy: {
      '/api': `http://127.0.0.1:${process.env.DASHBOARD_PORT || 7655}`,
    },
  },
  build: {
    outDir: 'dist',
  },
})

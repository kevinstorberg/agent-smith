import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4321,
    proxy: {
      '/api': 'http://localhost:7654',
    },
  },
  build: {
    outDir: 'dist',
  },
})

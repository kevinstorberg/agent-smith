import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
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

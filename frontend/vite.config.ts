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
    chunkSizeWarningLimit: 1700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('@uiw') || id.includes('@codemirror') || id.includes('@lezer')) return 'editor';
          if (id.includes('react-markdown') || id.includes('remark-') || id.includes('micromark') || id.includes('unified')) return 'markdown';
          if (id.includes('chart.js') || id.includes('react-chartjs-2')) return 'charts';
          if (id.includes('@hello-pangea')) return 'drag-drop';
          if (id.includes('react') || id.includes('scheduler')) return 'react';
          return 'vendor';
        },
      },
    },
  },
})

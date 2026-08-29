import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/review/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/drafts': 'http://localhost:8010',
      '/claim': 'http://localhost:8010',
    },
  },
})

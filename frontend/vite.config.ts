import { defineConfig } from 'vite'
import {fileURLToPath} from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    fs: {allow:[fileURLToPath(new URL('.',import.meta.url)),fileURLToPath(new URL('../assets/branding',import.meta.url))]},
    proxy: { '/api': { target: 'http://127.0.0.1:8766', changeOrigin: true } },
  },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8766', changeOrigin: true } } },
})

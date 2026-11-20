import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'
import { defineConfig } from 'vite'

const webRoot = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
const devHttps = process.env.VITE_DEV_HTTPS === '1' || process.env.VITE_DEV_HTTPS === 'true'
const devPort = Number(process.env.VITE_DEV_PORT || (devHttps ? 5174 : 5173))

export default defineConfig({
  envDir: webRoot,
  plugins: devHttps ? [react(), tailwindcss(), basicSsl()] : [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: devPort,
    strictPort: true,
    https: devHttps,
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
        ws: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})

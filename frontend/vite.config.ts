import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Disable timeout for SSE streams (agent may run for minutes)
        timeout: 0,
        // Prevent proxy from buffering SSE events
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Connection', 'keep-alive')
          })
          proxy.on('error', (err, _req, res) => {
            console.error('[vite proxy error]', err.message)
            if (res && 'writeHead' in res) {
              (res as any).writeHead?.(502, { 'Content-Type': 'application/json' })
              ;(res as any).end?.(JSON.stringify({ error: 'Proxy error', detail: err.message }))
            }
          })
        },
      },
    },
    watch: {
      // Exclude backend directory from Vite's file watcher to prevent
      // HMR full-reload when code agent writes files to backend/apps/
      ignored: ['**/backend/**', '**/node_modules/**'],
    },
  },
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server — /api aur /ws dono backend (localhost:8000) ko proxy hote hain.
// Browser kabhi localhost directly nahi call karta — relative URLs only.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Preview host (e2b.app) allow karna — dev ke liye sab hosts; production mein restrict karna
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})

import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  base: '/cosyvoice/',
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    host: '0.0.0.0', // Allow LAN access
    proxy: {
      '/conversation/v1/responses': {
        target: 'http://112.29.111.160:18011',
        changeOrigin: true,
      },
      '/ws/tts': {
        target: 'ws://10.1.30.4:18088',
        changeOrigin: true,
        ws: true
      }
    }
  }
})

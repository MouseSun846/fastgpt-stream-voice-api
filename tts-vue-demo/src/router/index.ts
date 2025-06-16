import { createRouter, createWebHistory } from 'vue-router'
import TTSDemo from '../components/TTSDemo.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'tts-demo',
      component: TTSDemo
    },
    {
      path: '/tts-demo',
      name: 'tts-demo-alt',
      component: TTSDemo
    }
  ]
})

export default router

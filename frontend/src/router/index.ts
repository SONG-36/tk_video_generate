import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import ImageGenerationView from '@/views/ImageGenerationView.vue'
import VideoGenerationView from '@/views/VideoGenerationView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: '/image-generation' },
        {
          path: 'image-generation',
          name: 'image-generation',
          component: ImageGenerationView,
          meta: { title: '生成图片' },
        },
        {
          path: 'video-generation',
          name: 'video-generation',
          component: VideoGenerationView,
          meta: { title: '生成视频' },
        },
      ],
    },
  ],
})

export default router


<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Picture, VideoCamera } from '@element-plus/icons-vue'

const route = useRoute()
const pageTitle = computed(() => String(route.meta.title ?? '工作台'))
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <span class="brand-mark">T</span>
        <div>
          <strong>TikTok 运营制作</strong>
          <small>Operations Studio</small>
        </div>
      </div>
      <el-menu :default-active="route.path" router class="side-menu">
        <el-menu-item index="/image-generation">
          <el-icon><Picture /></el-icon>
          <span>生成图片</span>
        </el-menu-item>
        <el-menu-item index="/video-generation">
          <el-icon><VideoCamera /></el-icon>
          <span>生成视频</span>
        </el-menu-item>
      </el-menu>
      <div class="phase-note">
        <span class="status-dot" />
        基础架构阶段
      </div>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div>
          <p class="eyebrow">内容生产工作台</p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <el-tag effect="plain" round>本地运行</el-tag>
      </el-header>
      <el-main class="main-content">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>


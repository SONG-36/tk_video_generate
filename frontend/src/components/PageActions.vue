<script setup lang="ts">
import { Plus } from '@element-plus/icons-vue'

defineProps<{ count: number; disabled?: boolean }>()
defineEmits<{ add: []; submit: [] }>()
</script>

<template>
  <div class="page-actions">
    <span>共 {{ count }} / 10 个任务</span>
    <div>
      <el-button
        :icon="Plus"
        :disabled="disabled || count >= 10"
        @click="$emit('add')"
      >
        添加任务
      </el-button>
      <el-button
        type="primary"
        :loading="disabled"
        :disabled="disabled"
        @click="$emit('submit')"
      >
        批量提交
      </el-button>
    </div>
  </div>
</template>

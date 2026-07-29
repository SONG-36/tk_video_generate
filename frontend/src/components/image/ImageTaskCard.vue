<script setup lang="ts">
import { Delete, Download, Loading } from '@element-plus/icons-vue'
import ReferenceUpload from '@/components/ReferenceUpload.vue'
import type { ImageCount, ImageRatio, ImageTask } from '@/types/tasks'

const props = defineProps<{
  task: ImageTask
  index: number
  disabled: boolean
  canDelete: boolean
}>()

const emit = defineEmits<{
  'update:task': [task: ImageTask]
  remove: []
}>()

function update(patch: Partial<ImageTask>) {
  emit('update:task', { ...props.task, ...patch })
}

function formatSize(bytes: number) {
  return `${Math.max(bytes / 1024, 0.1).toFixed(1)} KB`
}
</script>

<template>
  <article
    :id="task.id"
    class="task-card"
    :class="{ 'has-error': task.errors.length || task.status === 'FAILED' }"
  >
    <header class="task-header">
      <div>
        <span>任务 {{ String(index + 1).padStart(2, '0') }}</span>
        <strong>图片生成任务</strong>
        <el-tag
          v-if="task.status !== 'DRAFT'"
          size="small"
          :type="
            task.status === 'SUCCESS'
              ? 'success'
              : task.status === 'FAILED'
                ? 'danger'
                : 'warning'
          "
        >
          {{ task.status }}
        </el-tag>
      </div>
      <el-button
        text
        type="danger"
        :icon="Delete"
        :disabled="disabled || !canDelete"
        @click="$emit('remove')"
      >
        删除任务
      </el-button>
    </header>

    <el-alert
      v-if="task.errors.length"
      type="error"
      :closable="false"
      show-icon
      :title="task.errors.join('；')"
    />
    <el-alert
      v-else-if="task.status === 'FAILED'"
      type="error"
      :closable="false"
      show-icon
      :title="task.errorMessage || '图片生成失败'"
    />

    <div class="task-grid">
      <div class="field upload-field">
        <label>参考图片</label>
        <ReferenceUpload
          :files="task.files"
          :limit="5"
          :disabled="disabled"
          @change="(files) => update({ files })"
        />
      </div>
      <div class="field prompt-field">
        <label>提示词 <b>*</b></label>
        <el-input
          :model-value="task.prompt"
          type="textarea"
          :rows="7"
          maxlength="10000"
          show-word-limit
          :disabled="disabled"
          placeholder="描述画面主体、场景、光线、风格与构图"
          @update:model-value="(value: string) => update({ prompt: value })"
        />
      </div>
      <div class="field">
        <label>图片比例</label>
        <el-radio-group
          :model-value="task.ratio"
          :disabled="disabled"
          @update:model-value="(value: string | number | boolean) => update({ ratio: value as ImageRatio })"
        >
          <el-radio-button label="9:16" />
          <el-radio-button label="3:4" />
          <el-radio-button label="1:1" />
        </el-radio-group>
      </div>
      <div class="field">
        <label>图片数量</label>
        <el-radio-group
          :model-value="task.count"
          :disabled="disabled"
          @update:model-value="(value: string | number | boolean) => update({ count: value as ImageCount })"
        >
          <el-radio-button :label="1">1 张</el-radio-button>
          <el-radio-button :label="2">2 张</el-radio-button>
          <el-radio-button :label="4">4 张</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <div v-if="task.status === 'RUNNING' || task.status === 'PENDING'" class="task-progress">
      <el-icon class="is-loading"><Loading /></el-icon>
      后台正在{{ task.status === 'PENDING' ? '等待执行' : '生成图片' }}…
    </div>

    <div v-if="task.results.length" class="result-section">
      <div class="result-heading">
        <strong>生成结果</strong>
        <span>{{ task.results.length }} 张 PNG</span>
      </div>
      <div class="result-grid">
        <figure v-for="result in task.results" :key="result.id" class="result-card">
          <img :src="result.previewUrl" :alt="result.fileName">
          <figcaption>
            <div>
              <strong>{{ result.fileName }}</strong>
              <small>{{ formatSize(result.fileSize) }}</small>
            </div>
            <el-button
              tag="a"
              :href="result.downloadUrl"
              :icon="Download"
              size="small"
              download
            >
              下载
            </el-button>
          </figcaption>
        </figure>
      </div>
    </div>
  </article>
</template>

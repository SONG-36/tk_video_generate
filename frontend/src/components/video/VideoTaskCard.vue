<script setup lang="ts">
import { Delete, Download, Loading } from '@element-plus/icons-vue'
import ReferenceUpload from '@/components/ReferenceUpload.vue'
import type {
  DurationMode,
  FixedDuration,
  ReferenceMode,
  Resolution,
  VideoModel,
  VideoRatio,
  VideoTask,
} from '@/types/tasks'

const props = defineProps<{
  task: VideoTask
  index: number
  disabled: boolean
  canDelete: boolean
}>()

const emit = defineEmits<{
  'update:task': [task: VideoTask]
  remove: []
}>()

function update(patch: Partial<VideoTask>) {
  emit('update:task', { ...props.task, ...patch })
}

function updateReferenceMode(value: ReferenceMode) {
  update({
    referenceMode: value,
    files: value === '首帧图' ? props.task.files.slice(0, 1) : props.task.files,
  })
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
        <strong>视频生成任务</strong>
        <el-tag
          v-if="task.status !== 'DRAFT'"
          size="small"
          :type="task.status === 'SUCCESS' ? 'success' : task.status === 'FAILED' ? 'danger' : 'warning'"
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
      :title="task.errorMessage || '视频生成失败'"
    />

    <div class="task-grid">
      <div class="field">
        <label>参考模式</label>
        <el-radio-group
          :model-value="task.referenceMode"
          :disabled="disabled"
          @update:model-value="(value: string | number | boolean) => updateReferenceMode(value as ReferenceMode)"
        >
          <el-radio-button label="参考生成" />
          <el-radio-button label="首帧图" />
        </el-radio-group>
      </div>
      <div class="field upload-field">
        <label>参考图片</label>
        <ReferenceUpload
          :files="task.files"
          :limit="task.referenceMode === '首帧图' ? 1 : 5"
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
          maxlength="1000"
          show-word-limit
          :disabled="disabled"
          placeholder="描述主体运动、镜头轨迹、场景氛围与节奏……"
          @update:model-value="(value: string) => update({ prompt: value })"
        />
      </div>
      <div class="field">
        <label>分辨率</label>
        <el-radio-group
          :model-value="task.resolution"
          :disabled="disabled"
          @update:model-value="(value: string | number | boolean) => update({ resolution: value as Resolution })"
        >
          <el-radio-button label="480P" />
          <el-radio-button label="720P" />
        </el-radio-group>
      </div>
      <div class="field">
        <label>视频比例</label>
        <el-radio-group
          :model-value="task.ratio"
          :disabled="disabled"
          @update:model-value="(value: string | number | boolean) => update({ ratio: value as VideoRatio })"
        >
          <el-radio-button label="16:9" />
          <el-radio-button label="9:16" />
        </el-radio-group>
      </div>
      <div class="field">
        <label>时长模式</label>
        <el-radio-group
          :model-value="task.durationMode"
          :disabled="disabled"
          @update:model-value="(value: string | number | boolean) => update({ durationMode: value as DurationMode })"
        >
          <el-radio-button label="固定时长" />
          <el-radio-button label="智能时长" />
        </el-radio-group>
      </div>
      <div v-if="task.durationMode === '固定时长'" class="field">
        <label>固定时长</label>
        <el-input-number
          :model-value="task.fixedDuration"
          :min="4"
          :max="15"
          :step="1"
          :disabled="disabled"
          controls-position="right"
          @update:model-value="(value: number | undefined) => update({ fixedDuration: (value ?? 5) as FixedDuration })"
        />
      </div>
      <div class="field sound-field">
        <label>输出声音</label>
        <el-switch
          :model-value="task.sound"
          :disabled="disabled"
          active-text="开启"
          inactive-text="关闭"
          @update:model-value="(value: string | number | boolean) => update({ sound: Boolean(value) })"
        />
      </div>
      <div class="field">
        <label>视频模型</label>
        <el-select
          :model-value="task.model"
          :disabled="disabled"
          placeholder="请选择模型"
          @update:model-value="(value: string | number | boolean) => update({ model: value as VideoModel })"
        >
          <el-option label="Doubao-Seedance-2.0" value="doubao-seedance-2-0-260128" />
          <el-option label="Doubao-Seedance-2.0-mini" value="doubao-seedance-2-0-mini-260615" />
        </el-select>
      </div>
    </div>

    <div v-if="task.status === 'RUNNING' || task.status === 'PENDING'" class="task-progress">
      <el-icon class="is-loading"><Loading /></el-icon>
      后台正在{{ task.status === 'PENDING' ? '等待执行' : '生成视频' }}……
    </div>

    <div v-if="task.results.length" class="result-section">
      <div class="result-heading">
        <strong>生成结果</strong>
        <span>MP4</span>
      </div>
      <figure
        v-for="result in task.results"
        :key="result.id"
        class="result-card video-result-card"
      >
        <video :src="result.previewUrl" controls preload="metadata" />
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
  </article>
</template>

<script setup lang="ts">
import type { UploadFile, UploadFiles, UploadProps } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

const props = defineProps<{ files: File[]; limit: number; disabled?: boolean }>()
const emit = defineEmits<{ change: [files: File[]] }>()

function syncFiles(_: UploadFile, uploadFiles: UploadFiles) {
  emit(
    'change',
    uploadFiles.flatMap((item) => (item.raw ? [item.raw as File] : [])),
  )
}

const handleExceed: UploadProps['onExceed'] = (files) => {
  emit('change', [...props.files, ...files])
}
</script>

<template>
  <el-upload
    multiple
    action="#"
    :auto-upload="false"
    :limit="limit"
    :disabled="disabled"
    :on-change="syncFiles"
    :on-remove="syncFiles"
    :on-exceed="handleExceed"
    list-type="picture-card"
    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
  >
    <el-icon><Plus /></el-icon>
    <template #tip>
      <div class="upload-tip">
        JPG / JPEG / PNG，单张不超过 10MB，最多 {{ limit }} 张
      </div>
    </template>
  </el-upload>
</template>

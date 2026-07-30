<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type {
  UploadFile,
  UploadProps,
  UploadRawFile,
  UploadUserFile,
} from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

const props = defineProps<{ files: File[]; limit: number; disabled?: boolean }>()
const emit = defineEmits<{ change: [files: File[]] }>()
const displayFiles = ref<UploadUserFile[]>([])
let uploadFileSequence = Date.now()
const allowedExtensions = new Set(['jpg', 'jpeg', 'png'])
const allowedMimeTypes = new Set(['image/jpeg', 'image/png'])
const maxFileSize = 10 * 1024 * 1024

function rejectionReason(file: File): string | undefined {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!allowedExtensions.has(extension) || !allowedMimeTypes.has(file.type)) {
    return `${file.name}：格式不支持，仅支持 JPG、JPEG、PNG`
  }
  if (file.size > maxFileSize) {
    return `${file.name}：文件超过 10MB`
  }
  return undefined
}

function acceptFiles(files: File[]) {
  const accepted: File[] = []
  for (const file of files) {
    const reason = rejectionReason(file)
    if (reason) {
      ElMessage.warning(reason)
    } else if (accepted.length >= props.limit) {
      ElMessage.warning(`参考图片最多只能上传 ${props.limit} 张，${file.name} 未添加`)
    } else {
      accepted.push(file)
    }
  }
  // task.files 是编号和 @ 候选的唯一来源，先过滤再同步父状态和 Element Plus 列表。
  syncDisplayFiles(accepted)
  emit('change', accepted)
}

function rawFiles(uploadFiles: Array<{ raw?: UploadRawFile }>): File[] {
  return uploadFiles.flatMap((item) => (item.raw ? [item.raw as File] : []))
}

function syncFiles(_: UploadFile, uploadFiles: UploadFile[]) {
  acceptFiles(rawFiles(uploadFiles))
}

const handleExceed: UploadProps['onExceed'] = (files, uploadFiles) => {
  acceptFiles([...rawFiles(uploadFiles), ...(files as File[])])
}

function syncDisplayFiles(files: File[]) {
  const existing = new Map(
    displayFiles.value.flatMap((item) => (item.raw ? [[item.raw as File, item]] : [])),
  )
  const retained = new Set(files)
  for (const item of displayFiles.value) {
    const raw = item.raw as File | undefined
    if (raw && !retained.has(raw) && item.url?.startsWith('blob:')) {
      URL.revokeObjectURL(item.url)
    }
  }
  displayFiles.value = files.map((file) => {
    const current = existing.get(file)
    if (current) return current
    const raw = file as UploadRawFile
    raw.uid ??= ++uploadFileSequence
    return {
      name: file.name,
      size: file.size,
      status: 'ready',
      uid: raw.uid,
      raw,
      url: URL.createObjectURL(file),
    }
  })
}

watch(() => props.files, syncDisplayFiles, { immediate: true })

onBeforeUnmount(() => {
  for (const item of displayFiles.value) {
    if (item.url?.startsWith('blob:')) URL.revokeObjectURL(item.url)
  }
})
</script>

<template>
  <el-upload
    v-model:file-list="displayFiles"
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

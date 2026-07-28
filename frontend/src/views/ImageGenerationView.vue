<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import ImageTaskCard from '@/components/image/ImageTaskCard.vue'
import PageActions from '@/components/PageActions.vue'
import {
  fetchImageBatchStatus,
  submitImageBatch,
  type ImageBatchStatus,
} from '@/api/image'
import type { ImageTask } from '@/types/tasks'
import { validateImageTask } from '@/utils/validation'

let sequence = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined

const createTask = (): ImageTask => ({
  id: `image-task-${++sequence}`,
  prompt: '',
  files: [],
  ratio: '9:16',
  count: 1,
  errors: [],
  status: 'DRAFT',
  results: [],
})

const tasks = ref<ImageTask[]>([createTask()])
const submitting = ref(false)
const batchId = ref<number>()
const batchStatus = ref<ImageBatchStatus['status']>()
const locked = computed(
  () =>
    submitting.value ||
    batchStatus.value === 'PENDING' ||
    batchStatus.value === 'RUNNING',
)

function addTask() {
  if (locked.value) return
  if (tasks.value.length >= 10) {
    ElMessage.warning('最多只能添加 10 个任务')
    return
  }
  tasks.value.push(createTask())
}

function updateTask(index: number, task: ImageTask) {
  tasks.value[index] = task
}

function removeTask(index: number) {
  if (locked.value) return
  if (tasks.value.length === 1) {
    ElMessage.warning('至少保留一个任务')
    return
  }
  tasks.value.splice(index, 1)
}

async function submit() {
  if (locked.value) return
  tasks.value.forEach((task) => {
    task.errors = validateImageTask(task)
    task.errorMessage = undefined
  })
  const firstInvalid = tasks.value.find((task) => task.errors.length)
  if (firstInvalid) {
    await nextTick()
    document
      .getElementById(firstInvalid.id)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    ElMessage.error('存在校验失败的任务，请检查红色提示')
    return
  }

  try {
    await ElMessageBox.confirm('是否确认提交任务', '提交确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }

  submitting.value = true
  try {
    const created = await submitImageBatch(tasks.value)
    batchId.value = created.batch_id
    batchStatus.value = created.status
    created.tasks.forEach((item) => {
      const task = tasks.value[item.client_index]
      if (task) {
        task.serverTaskId = item.task_id
        task.status = 'PENDING'
        task.results = []
      }
    })
    ElMessage.success('任务已提交，正在后台生成')
    schedulePoll(0)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    submitting.value = false
  }
}

function schedulePoll(delay = 2000) {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(poll, delay)
}

async function poll() {
  if (!batchId.value) return
  try {
    const status = await fetchImageBatchStatus(batchId.value)
    batchStatus.value = status.status
    status.tasks.forEach((serverTask) => {
      const task = tasks.value.find((item) => item.serverTaskId === serverTask.id)
      if (!task) return
      task.status = serverTask.status
      task.errorMessage = serverTask.error_message ?? undefined
      task.results = serverTask.results.map((result) => ({
        id: result.id,
        fileName: result.file_name,
        fileSize: result.file_size,
        previewUrl: result.preview_url,
        downloadUrl: result.download_url,
      }))
    })
    if (status.tasks.every((task) => task.status === 'SUCCESS' || task.status === 'FAILED')) {
      const message =
        status.failed_tasks > 0
          ? `批次执行完成：${status.success_tasks} 个成功，${status.failed_tasks} 个失败`
          : '全部图片生成成功'
      status.failed_tasks > 0 ? ElMessage.warning(message) : ElMessage.success(message)
      return
    }
    schedulePoll()
  } catch (error) {
    ElMessage.error(`状态查询失败：${getErrorMessage(error)}`)
    schedulePoll(4000)
  }
}

function getErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    return String(error.response?.data?.message ?? error.message ?? '请求失败')
  }
  return error instanceof Error ? error.message : '请求失败'
}

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<template>
  <section class="workspace">
    <div class="intro">
      <div>
        <h2>图片生成任务</h2>
        <p>批量配置任务，提交后系统将异步生成并自动刷新结果。</p>
      </div>
      <div class="intro-status">
        <el-tag v-if="batchId" effect="plain">批次 #{{ batchId }}</el-tag>
        <span class="step-pill">
          {{ locked ? '02 · 生成中' : batchStatus ? '03 · 已完成' : '01 · 配置任务' }}
        </span>
      </div>
    </div>

    <PageActions
      :count="tasks.length"
      :disabled="locked"
      @add="addTask"
      @submit="submit"
    />

    <div class="task-list">
      <ImageTaskCard
        v-for="(task, index) in tasks"
        :key="task.id"
        :task="task"
        :index="index"
        :disabled="locked"
        :can-delete="tasks.length > 1"
        @update:task="(value) => updateTask(index, value)"
        @remove="removeTask(index)"
      />
    </div>

    <PageActions
      :count="tasks.length"
      :disabled="locked"
      @add="addTask"
      @submit="submit"
    />
  </section>
</template>

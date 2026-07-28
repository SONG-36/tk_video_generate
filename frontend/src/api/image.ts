import { apiClient } from '@/api/client'
import type { ImageTask, ImageRatio } from '@/types/tasks'

export type BatchStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'PARTIAL_SUCCESS' | 'FAILED'
export type TaskStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'

interface ImageBatchCreated {
  batch_id: number
  status: BatchStatus
  tasks: Array<{ client_index: number; task_id: number }>
}

interface ImageTaskStatusDto {
  id: number
  status: TaskStatus
  prompt: string
  aspect_ratio: ImageRatio
  image_count: number
  error_code: string | null
  error_message: string | null
  results: Array<{
    id: number
    file_name: string
    file_size: number
    preview_url: string
    download_url: string
  }>
}

export interface ImageBatchStatus {
  batch_id: number
  status: BatchStatus
  total_tasks: number
  success_tasks: number
  failed_tasks: number
  tasks: ImageTaskStatusDto[]
}

export async function submitImageBatch(tasks: ImageTask[]): Promise<ImageBatchCreated> {
  const form = new FormData()
  form.append(
    'payload',
    JSON.stringify({
      tasks: tasks.map((task) => ({
        prompt: task.prompt.trim(),
        aspect_ratio: task.ratio,
        image_count: task.count,
        reference_images: task.files.map((file) => file.name),
      })),
    }),
  )
  tasks.forEach((task, index) => {
    task.files.forEach((file) => form.append(`references_${index}`, file, file.name))
  })
  const response = await apiClient.post<ImageBatchCreated>('/image/batches', form, {
    timeout: 60_000,
  })
  return response.data
}

export async function fetchImageBatchStatus(batchId: number): Promise<ImageBatchStatus> {
  const response = await apiClient.get<ImageBatchStatus>(
    `/image/batches/${batchId}/status`,
  )
  return response.data
}


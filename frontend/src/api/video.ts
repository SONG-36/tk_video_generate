import { apiClient } from '@/api/client'
import type {
  DurationMode,
  ReferenceMode,
  Resolution,
  VideoRatio,
  VideoTask,
} from '@/types/tasks'
import type { BatchStatus, TaskStatus } from '@/api/image'

interface VideoBatchCreated {
  batch_id: number
  status: BatchStatus
  tasks: Array<{ client_index: number; task_id: number }>
}

interface VideoTaskStatusDto {
  id: number
  status: TaskStatus
  prompt: string
  reference_mode: 'REFERENCE' | 'FIRST_FRAME'
  resolution: Resolution
  aspect_ratio: VideoRatio
  duration_mode: 'FIXED' | 'SMART'
  fixed_duration: number | null
  output_sound: boolean
  model: 'doubao-seedance-2-0-260128' | 'doubao-seedance-2-0-mini-260615'
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

export interface VideoBatchStatus {
  batch_id: number
  status: BatchStatus
  total_tasks: number
  success_tasks: number
  failed_tasks: number
  tasks: VideoTaskStatusDto[]
}

const referenceModeMap: Record<ReferenceMode, 'REFERENCE' | 'FIRST_FRAME'> = {
  参考生成: 'REFERENCE',
  首帧图: 'FIRST_FRAME',
}

const durationModeMap: Record<DurationMode, 'FIXED' | 'SMART'> = {
  固定时长: 'FIXED',
  智能时长: 'SMART',
}

export async function submitVideoBatch(tasks: VideoTask[]): Promise<VideoBatchCreated> {
  const form = new FormData()
  form.append(
    'payload',
    JSON.stringify({
      tasks: tasks.map((task) => ({
        prompt: task.prompt.trim(),
        reference_mode: referenceModeMap[task.referenceMode],
        resolution: task.resolution,
        aspect_ratio: task.ratio,
        duration_mode: durationModeMap[task.durationMode],
        fixed_duration: task.durationMode === '固定时长' ? task.fixedDuration : null,
        output_sound: task.sound,
        model: task.model,
        reference_images: task.files.map((file) => file.name),
      })),
    }),
  )
  tasks.forEach((task, index) => {
    task.files.forEach((file) => form.append(`references_${index}`, file, file.name))
  })
  const response = await apiClient.post<VideoBatchCreated>('/video/batches', form, {
    timeout: 60_000,
  })
  return response.data
}

export async function fetchVideoBatchStatus(batchId: number): Promise<VideoBatchStatus> {
  const response = await apiClient.get<VideoBatchStatus>(
    `/video/batches/${batchId}/status`,
  )
  return response.data
}

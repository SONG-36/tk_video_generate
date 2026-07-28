export type ImageRatio = '9:16' | '3:4' | '1:1'
export type ImageCount = 1 | 2 | 4
export type ReferenceMode = '参考生成' | '首帧图'
export type Resolution = '480P' | '720P'
export type VideoRatio = '16:9' | '9:16'
export type DurationMode = '固定时长' | '智能时长'
export type FixedDuration = 5 | 10 | 15
export type GenerationTaskStatus =
  | 'DRAFT'
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCESS'
  | 'FAILED'

export interface BaseTask {
  id: string
  prompt: string
  files: File[]
  errors: string[]
}

export interface GenerationResult {
  id: number
  fileName: string
  fileSize: number
  previewUrl: string
  downloadUrl: string
}

export interface ImageTask extends BaseTask {
  ratio: ImageRatio
  count: ImageCount
  serverTaskId?: number
  status: GenerationTaskStatus
  errorMessage?: string
  results: GenerationResult[]
}

export type ImageGenerationResult = GenerationResult

export interface VideoTask extends BaseTask {
  referenceMode: ReferenceMode
  resolution: Resolution
  ratio: VideoRatio
  durationMode: DurationMode
  fixedDuration: FixedDuration
  sound: boolean
  serverTaskId?: number
  status: GenerationTaskStatus
  errorMessage?: string
  results: GenerationResult[]
}

import type { ImageTask, VideoTask } from '@/types/tasks'

const allowedExtensions = new Set(['jpg', 'jpeg', 'png'])
const allowedMimeTypes = new Set(['image/jpeg', 'image/png'])
const maxFileSize = 10 * 1024 * 1024

function validateCommon(prompt: string, files: File[], maxFiles = 5): string[] {
  const errors: string[] = []
  if (!prompt.trim()) errors.push('请输入提示词')
  if (files.length > maxFiles) errors.push(`参考图片不能超过 ${maxFiles} 张`)
  files.forEach((file) => {
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (!allowedExtensions.has(extension) || !allowedMimeTypes.has(file.type)) {
      errors.push(`${file.name}：仅支持 JPG、JPEG、PNG，且文件类型必须匹配`)
    }
    if (file.size > maxFileSize) errors.push(`${file.name}：文件不能超过 10MB`)
  })
  return errors
}

export function validateImageTask(task: ImageTask): string[] {
  return validateCommon(task.prompt, task.files)
}

export function validateVideoTask(task: VideoTask): string[] {
  const maxFiles = task.referenceMode === '首帧图' ? 1 : 5
  const errors = validateCommon(task.prompt, task.files, maxFiles)
  if (task.referenceMode === '首帧图' && task.files.length !== 1) {
    errors.push('首帧图模式必须上传且只能上传 1 张图片')
  }
  if (
    task.durationMode === '固定时长' &&
    !([5, 10, 15] as number[]).includes(task.fixedDuration)
  ) {
    errors.push('请选择合法的固定时长')
  }
  return errors
}

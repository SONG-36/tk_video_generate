import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { submitVideoBatch } from '@/api/video'
import type { VideoTask } from '@/types/tasks'

vi.mock('@/api/client', () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({
      data: { batch_id: 1, status: 'PENDING', tasks: [{ client_index: 0, task_id: 1 }] },
    }),
  },
}))

function task(prompt: string): VideoTask {
  return {
    id: 'video-api-test',
    prompt,
    files: [
      new File(['girl'], 'girl.png', { type: 'image/png' }),
      new File(['product'], 'product.png', { type: 'image/png' }),
    ],
    referenceMode: '参考生成',
    resolution: '720P',
    ratio: '9:16',
    durationMode: '智能时长',
    fixedDuration: 5,
    sound: false,
    model: 'doubao-seedance-2-0-mini-260615',
    errors: [],
    status: 'DRAFT',
    results: [],
  }
}

describe('video API prompt submission', () => {
  beforeEach(() => {
    vi.mocked(apiClient.post).mockClear()
  })

  it.each([
    '请参考图片1，让图片2中的人物也xxx',
    '请参考@图片1，让图片2中的人物也xxx',
    '请参考@图片1，让@图片2中的人物也xxx',
  ])('submits the original mention markers for %s', async (prompt) => {
    await submitVideoBatch([task(`  ${prompt}  `)])

    const form = vi.mocked(apiClient.post).mock.calls[0][1] as FormData
    const payload = JSON.parse(String(form.get('payload')))
    expect(payload.tasks[0].prompt).toBe(prompt)
    expect(form.getAll('references_0')).toHaveLength(2)
  })
})

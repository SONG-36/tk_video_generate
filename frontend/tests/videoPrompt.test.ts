import { describe, expect, it } from 'vitest'
import {
  getReferenceImageItems,
  insertVideoImageReference,
  normalizeVideoImageReferences,
  remapVideoImageReferences,
  validateVideoImageReferences,
} from '@/utils/videoPrompt'
import { unicodeLength, validateVideoTask } from '@/utils/validation'
import type { VideoTask } from '@/types/tasks'

function file(name: string): File {
  return new File([name], name, { type: 'image/png' })
}

describe('video image references', () => {
  it('normalizes only valid image mentions', () => {
    const prompt =
      '联系 user@example.com 或 user@图片1.com，单独的 @ 保留；让@图片1拿起@图片5'

    expect(normalizeVideoImageReferences(prompt)).toBe(
      '联系 user@example.com 或 user@图片1.com，单独的 @ 保留；让图片1拿起图片5',
    )
  })

  it('rejects missing and invalid image numbers', () => {
    expect(validateVideoImageReferences('让@图片6进入镜头', 5)).toEqual([
      '提示词引用了不存在的 @图片6，当前只有 5 张参考图',
    ])
    expect(validateVideoImageReferences('@图片0', 5)[0]).toContain('格式不合法')
    expect(validateVideoImageReferences('@图片-1', 5)[0]).toContain('格式不合法')
    expect(validateVideoImageReferences('@图片1.5', 5)[0]).toContain('格式不合法')
    expect(validateVideoImageReferences('首帧引用@图片2', 1)).toEqual([
      '提示词引用了不存在的 @图片2，当前只有 1 张参考图',
    ])
  })

  it('keeps standalone at signs and direct 图片N text compatible', () => {
    expect(validateVideoImageReferences('邮箱 a@b.com，图片1，@', 1)).toEqual([])
    expect(normalizeVideoImageReferences('邮箱 a@b.com，图片1，@')).toBe(
      '邮箱 a@b.com，图片1，@',
    )
  })

  it.each([
    '@图片0',
    '@图片-1',
    '@图片1.5',
    '@图片01',
    '@图片已删除',
  ])('rejects malformed structured reference %s', (reference) => {
    expect(validateVideoImageReferences(reference, 2)).not.toEqual([])
  })

  it.each([
    '图片1',
    '图片2',
    '普通图片9',
    'user@example.com',
    'user@图片1.com',
    '@',
    '@abc',
    '@人物',
  ])('keeps compatible text %s unchanged', (prompt) => {
    expect(validateVideoImageReferences(prompt, 2)).toEqual([])
    expect(normalizeVideoImageReferences(prompt)).toBe(prompt)
  })

  it('normalizes repeated and out-of-order mentions at different positions', () => {
    const prompt = '@图片2，先看@图片1；again @图片1.'
    expect(validateVideoImageReferences(prompt, 2)).toEqual([])
    expect(normalizeVideoImageReferences(prompt)).toBe('图片2，先看图片1；again 图片1.')
    expect(validateVideoImageReferences('@图片3 @图片999', 2)).toHaveLength(2)
  })

  it('renumbers the visible list after the second image is deleted', () => {
    const first = file('first.png')
    const second = file('second.png')
    const third = file('third.png')
    const before = getReferenceImageItems([first, second, third])
    const after = getReferenceImageItems([first, third])

    expect(after.map((item) => [item.label, item.file.name])).toEqual([
      ['图片1', 'first.png'],
      ['图片2', 'third.png'],
    ])
    expect(after[0].id).toBe(before[0].id)
    expect(after[1].id).toBe(before[2].id)
    expect(
      remapVideoImageReferences(
        '让@图片1看向@图片2，再拿起@图片3',
        [first, second, third],
        [first, third],
      ),
    ).toBe('让@图片1看向@图片已删除，再拿起@图片2')
    expect(validateVideoImageReferences('@图片已删除', 2)).toEqual([
      '提示词引用的图片已被删除，请重新选择图片引用',
    ])
  })

  it('inserts a selected mention at the current replacement range', () => {
    expect(insertVideoImageReference('让@展示', 1, 2, 2)).toEqual({
      value: '让@图片2展示',
      cursor: 5,
    })
  })

  it('does not restore a deleted reference for a same-name or same-content File', () => {
    const original = new File(['same'], 'same.png', { type: 'image/png' })
    const replacement = new File(['same'], 'same.png', { type: 'image/png' })
    expect(remapVideoImageReferences('@图片1', [original], [replacement])).toBe(
      '@图片已删除',
    )
  })

  it('counts Unicode code points consistently at the 10000-character boundary', () => {
    expect(unicodeLength('中文abc😀')).toBe(6)
    expect(unicodeLength('😀'.repeat(10000))).toBe(10000)
    const baseTask: VideoTask = {
      id: 'unicode-test',
      prompt: '😀'.repeat(10000),
      files: [],
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
    expect(validateVideoTask(baseTask)).toEqual([])
    expect(
      validateVideoTask({ ...baseTask, prompt: '😀'.repeat(10001) }),
    ).toContain('提示词不能超过 10000 字符')
  })
})

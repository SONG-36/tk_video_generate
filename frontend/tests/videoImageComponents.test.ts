/* eslint-disable vue/one-component-per-file */
import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'
import ReferenceUpload from '@/components/ReferenceUpload.vue'
import ImageMentionInput from '@/components/video/ImageMentionInput.vue'

function file(name: string, options: { type?: string; size?: number } = {}): File {
  return new File(
    [new Uint8Array(options.size ?? name.length)],
    name,
    { type: options.type ?? 'image/png' },
  )
}

const ElUploadStub = defineComponent({
  name: 'ElUpload',
  props: {
    fileList: { type: Array, default: () => [] },
    onChange: { type: Function, default: undefined },
    onExceed: { type: Function, default: undefined },
  },
  emits: ['update:fileList'],
  template: '<div class="upload-stub"><slot /><slot name="tip" /></div>',
})

const ElInputStub = defineComponent({
  name: 'ElInput',
  props: {
    modelValue: { type: String, default: '' },
  },
  emits: [
    'update:modelValue',
    'keydown',
    'click',
    'blur',
    'compositionstart',
    'compositionend',
  ],
  setup(props, { emit, expose }) {
    const textarea = ref<HTMLTextAreaElement>()
    expose({
      textarea,
      focus: () => textarea.value?.focus(),
    })
    return { props, emit, textarea }
  },
  template: `
    <textarea
      ref="textarea"
      :value="modelValue"
      @input="emit('update:modelValue', $event.target.value)"
      @keydown="emit('keydown', $event)"
      @click="emit('click', $event)"
      @blur="emit('blur', $event)"
      @compositionstart="emit('compositionstart', $event)"
      @compositionend="emit('compositionend', $event)"
    />
  `,
})

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn((value: File) => `blob:${value.name}`),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  })
})

describe('ReferenceUpload', () => {
  it('does not emit over-limit files into task state', () => {
    const warning = vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined)
    const wrapper = mount(ReferenceUpload, {
      props: { files: [file('one.png')], limit: 1 },
      global: { stubs: { ElUpload: ElUploadStub, ElIcon: true } },
    })

    const upload = wrapper.findComponent(ElUploadStub)
    upload.props('onExceed')?.([file('two.png')], upload.props('fileList'))

    const changes = wrapper.emitted('change') ?? []
    expect(changes[changes.length - 1]).toEqual([[wrapper.props('files')[0]]])
    expect(
      warning.mock.calls.some(([message]) => String(message).includes('最多只能上传 1 张')),
    ).toBe(true)
  })

  it('synchronizes the controlled upload list after a file is deleted', async () => {
    const first = file('first.png')
    const second = file('second.png')
    const wrapper = mount(ReferenceUpload, {
      props: { files: [first, second], limit: 5 },
      global: { stubs: { ElUpload: ElUploadStub, ElIcon: true } },
    })

    await wrapper.setProps({ files: [first] })

    const displayed = wrapper.findComponent(ElUploadStub).props('fileList') as Array<{
      raw: File
    }>
    expect(displayed.map((item) => item.raw.name)).toEqual(['first.png'])
  })

  it.each([
    [file('bad.gif', { type: 'image/gif' }), '格式不支持'],
    [file('large.png', { size: 10 * 1024 * 1024 + 1 }), '文件超过 10MB'],
  ])('rejects invalid files before emitting task state', (invalid, expectedMessage) => {
    const valid = file('valid.png')
    const warning = vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined)
    const wrapper = mount(ReferenceUpload, {
      props: { files: [valid], limit: 5 },
      global: { stubs: { ElUpload: ElUploadStub, ElIcon: true } },
    })
    const upload = wrapper.findComponent(ElUploadStub)

    upload.props('onChange')?.(
      { raw: invalid },
      [{ raw: valid }, { raw: invalid }],
    )

    const changes = wrapper.emitted('change') ?? []
    expect(changes[changes.length - 1]).toEqual([[valid]])
    expect(warning.mock.calls.some(([message]) => String(message).includes(expectedMessage))).toBe(true)
  })

  it('keeps valid files from a mixed selection and excludes invalid files from mentions', async () => {
    const existing = file('existing.png')
    const valid = file('new.png')
    const invalid = file('bad.txt', { type: 'text/plain' })
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined)
    const wrapper = mount(ReferenceUpload, {
      props: { files: [existing], limit: 5 },
      global: { stubs: { ElUpload: ElUploadStub, ElIcon: true } },
    })

    wrapper.findComponent(ElUploadStub).props('onChange')?.(
      { raw: invalid },
      [{ raw: existing }, { raw: valid }, { raw: invalid }],
    )
    const changes = wrapper.emitted('change') ?? []
    const accepted = changes[changes.length - 1][0] as File[]
    expect(accepted).toEqual([existing, valid])
    wrapper.unmount()

    const mentions = mount(ImageMentionInput, {
      props: { modelValue: '', files: accepted },
      global: { stubs: { ElInput: ElInputStub } },
    })
    await mentions.get('textarea').setValue('@')
    await nextTick()
    expect(mentions.text()).toContain('existing.png')
    expect(mentions.text()).toContain('new.png')
    expect(mentions.text()).not.toContain('bad.txt')
  })

  it.each([
    [1, 'second.png'],
    [5, 'sixth.png'],
  ])('rejects files beyond limit %i without removing existing files', (limit, rejectedName) => {
    const existing = Array.from({ length: limit }, (_, index) => file(`existing-${index}.png`))
    const extra = file(rejectedName)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined)
    const wrapper = mount(ReferenceUpload, {
      props: { files: existing, limit },
      global: { stubs: { ElUpload: ElUploadStub, ElIcon: true } },
    })

    wrapper.findComponent(ElUploadStub).props('onExceed')?.(
      [extra],
      existing.map((raw) => ({ raw })),
    )

    const changes = wrapper.emitted('change') ?? []
    expect(changes[changes.length - 1]).toEqual([existing])
  })
})

describe('ImageMentionInput', () => {
  it('shows current images after @ and inserts the selected image', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: {
        modelValue: '',
        files: [file('girl.png'), file('product.png')],
      },
      global: { stubs: { ElInput: ElInputStub } },
    })
    const textarea = wrapper.get('textarea')

    await textarea.setValue('@')
    await nextTick()

    expect(wrapper.findAll('.image-mention-option')).toHaveLength(2)
    expect(wrapper.text()).toContain('图片1')
    expect(wrapper.text()).toContain('product.png')
    await wrapper.findAll('.image-mention-option')[1].trigger('mousedown')

    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]).toEqual(['@图片2'])
  })

  it('shows an upload hint when @ is typed without images', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: { modelValue: '', files: [] },
      global: { stubs: { ElInput: ElInputStub } },
    })

    await wrapper.get('textarea').setValue('@')
    await nextTick()

    expect(wrapper.text()).toContain('请先上传参考图片')
  })

  it('shows only 图片1 for a first-frame file list', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: { modelValue: '', files: [file('first-frame.png')] },
      global: { stubs: { ElInput: ElInputStub } },
    })

    await wrapper.get('textarea').setValue('@')
    await nextTick()

    expect(wrapper.findAll('.image-mention-option')).toHaveLength(1)
    expect(wrapper.text()).toContain('图片1')
    expect(wrapper.text()).not.toContain('图片2')
  })

  it('does not open the image menu for an email at sign', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: { modelValue: '', files: [file('first.png')] },
      global: { stubs: { ElInput: ElInputStub } },
    })

    await wrapper.get('textarea').setValue('user@')
    await nextTick()

    expect(wrapper.find('.image-mention-menu').exists()).toBe(false)
  })

  it('keeps the menu closed after Escape and after Enter selection', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: { modelValue: '', files: [file('first.png')] },
      global: { stubs: { ElInput: ElInputStub } },
    })
    const textarea = wrapper.get('textarea')
    await textarea.setValue('@')
    await nextTick()
    await textarea.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.image-mention-menu').exists()).toBe(false)

    await textarea.setValue('@')
    await nextTick()
    await textarea.trigger('keydown', { key: 'Enter' })
    await nextTick()
    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]).toEqual(['@图片1'])
    expect(wrapper.find('.image-mention-menu').exists()).toBe(false)
  })

  it('supports ArrowDown and ArrowUp before Enter', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: {
        modelValue: '',
        files: [file('first.png'), file('second.png'), file('third.png')],
      },
      global: { stubs: { ElInput: ElInputStub } },
    })
    const textarea = wrapper.get('textarea')
    await textarea.setValue('@')
    await nextTick()
    await textarea.trigger('keydown', { key: 'ArrowDown' })
    await textarea.trigger('keydown', { key: 'ArrowDown' })
    await textarea.trigger('keydown', { key: 'ArrowUp' })
    await textarea.trigger('keydown', { key: 'Enter' })
    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]).toEqual(['@图片2'])
  })

  it('does not select during IME composition and resumes after compositionend', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: { modelValue: '', files: [file('first.png')] },
      global: { stubs: { ElInput: ElInputStub } },
    })
    const textarea = wrapper.get('textarea')
    await textarea.setValue('@')
    await nextTick()
    const updateCount = wrapper.emitted('update:modelValue')?.length ?? 0
    await textarea.trigger('compositionstart')
    await textarea.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.emitted('update:modelValue')).toHaveLength(updateCount)

    await textarea.trigger('compositionend')
    await nextTick()
    await textarea.trigger('keydown', { key: 'Enter' })
    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]).toEqual(['@图片1'])
  })

  it('inserts a mention at a caret in the middle of text', async () => {
    const wrapper = mount(ImageMentionInput, {
      props: { modelValue: '前@后', files: [file('first.png')] },
      global: { stubs: { ElInput: ElInputStub } },
    })
    const textarea = wrapper.get('textarea').element as HTMLTextAreaElement
    textarea.setSelectionRange(2, 2)
    await wrapper.get('textarea').trigger('click')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]).toEqual(['前@图片1后'])
  })
})

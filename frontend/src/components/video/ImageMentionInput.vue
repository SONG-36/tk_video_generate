<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  getReferenceImageItems,
  insertVideoImageReference,
} from '@/utils/videoPrompt'
import { unicodeLength } from '@/utils/validation'

interface TextareaExpose {
  textarea?: HTMLTextAreaElement
  $el?: HTMLElement
  focus?: () => void
}

const props = defineProps<{
  modelValue: string
  files: File[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const inputRef = ref<TextareaExpose>()
const menuOpen = ref(false)
const activeIndex = ref(0)
const mentionStart = ref(0)
const isComposing = ref(false)
const previewUrls = new Map<File, string>()
const promptLength = computed(() => unicodeLength(props.modelValue))

const items = computed(() =>
  getReferenceImageItems(props.files).map((item) => ({
    ...item,
    previewUrl: previewUrl(item.file),
  })),
)

function previewUrl(file: File): string {
  const existing = previewUrls.get(file)
  if (existing) return existing
  const url = URL.createObjectURL(file)
  previewUrls.set(file, url)
  return url
}

function getTextarea(): HTMLTextAreaElement | null {
  return inputRef.value?.textarea ?? inputRef.value?.$el?.querySelector('textarea') ?? null
}

function updateMenu(value = props.modelValue) {
  if (props.disabled) {
    menuOpen.value = false
    return
  }
  const textarea = getTextarea()
  const cursor = textarea?.selectionStart ?? value.length
  const candidate = value
    .slice(0, cursor)
    .match(/(?<![A-Za-z0-9._%+-])@(?:图片\d*)?$/)
  if (!candidate) {
    menuOpen.value = false
    return
  }
  mentionStart.value = cursor - candidate[0].length
  activeIndex.value = Math.min(activeIndex.value, Math.max(items.value.length - 1, 0))
  menuOpen.value = true
}

function handleInput(value: string) {
  emit('update:modelValue', value)
  if (!isComposing.value) void nextTick(() => updateMenu(value))
}

function insertMention(imageNumber: number) {
  const textarea = getTextarea()
  const currentValue = textarea?.value ?? props.modelValue
  const replaceEnd = textarea?.selectionStart ?? currentValue.length
  const inserted = insertVideoImageReference(
    currentValue,
    mentionStart.value,
    replaceEnd,
    imageNumber,
  )
  emit('update:modelValue', inserted.value)
  menuOpen.value = false
  void nextTick(() => {
    const currentTextarea = getTextarea()
    inputRef.value?.focus?.()
    currentTextarea?.setSelectionRange(inserted.cursor, inserted.cursor)
  })
}

function handleKeydown(event: KeyboardEvent) {
  // IME 组合输入期间的 Enter/方向键属于候选词操作，不能被图片菜单截获。
  if (event.isComposing || isComposing.value) return
  if (!menuOpen.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    menuOpen.value = false
    return
  }
  if (!items.value.length) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % items.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + items.value.length) % items.value.length
  } else if (event.key === 'Enter') {
    event.preventDefault()
    insertMention(items.value[activeIndex.value].number)
  }
}

function handleCompositionStart() {
  isComposing.value = true
}

function handleCompositionEnd() {
  isComposing.value = false
  void nextTick(() => updateMenu(getTextarea()?.value ?? props.modelValue))
}

function handleBlur() {
  window.setTimeout(() => {
    menuOpen.value = false
  }, 100)
}

watch(
  () => props.files,
  (files) => {
    const current = new Set(files)
    for (const [file, url] of previewUrls) {
      if (!current.has(file)) {
        URL.revokeObjectURL(url)
        previewUrls.delete(file)
      }
    }
    activeIndex.value = Math.min(activeIndex.value, Math.max(files.length - 1, 0))
  },
)

onBeforeUnmount(() => {
  for (const url of previewUrls.values()) URL.revokeObjectURL(url)
  previewUrls.clear()
})
</script>

<template>
  <div class="image-mention-input">
    <el-input
      ref="inputRef"
      :model-value="modelValue"
      type="textarea"
      :rows="7"
      :disabled="disabled"
      placeholder="描述主体运动、镜头轨迹、场景氛围与节奏；输入 @ 可引用图片"
      @update:model-value="handleInput"
      @keydown="handleKeydown"
      @click="updateMenu()"
      @blur="handleBlur"
      @compositionstart="handleCompositionStart"
      @compositionend="handleCompositionEnd"
    />
    <div class="image-mention-count" :class="{ 'is-error': promptLength > 10000 }">
      {{ promptLength }} / 10000
    </div>
    <div v-if="menuOpen" class="image-mention-menu" role="listbox">
      <div v-if="!items.length" class="image-mention-empty">请先上传参考图片</div>
      <button
        v-for="(item, index) in items"
        :key="item.id"
        type="button"
        class="image-mention-option"
        :class="{ 'is-active': index === activeIndex }"
        role="option"
        :aria-selected="index === activeIndex"
        @mouseenter="activeIndex = index"
        @mousedown.prevent="insertMention(item.number)"
      >
        <img :src="item.previewUrl" :alt="item.label">
        <span>
          <strong>{{ item.label }}</strong>
          <small>{{ item.file.name }}</small>
        </span>
      </button>
    </div>
  </div>
</template>

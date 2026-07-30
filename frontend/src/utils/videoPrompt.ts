const VALID_IMAGE_REFERENCE = /(?<![A-Za-z0-9._%+-])@图片([1-9]\d*)(?!\d|\.\d)/g
const INVALID_IMAGE_REFERENCE =
  /(?<![A-Za-z0-9._%+-])@图片(?:0\d*|-\d+|\+\d+|\d+\.\d+|(?!(?:[1-9]\d*))(?=\S|$))/

let referenceFileSequence = 0
const referenceFileIds = new WeakMap<File, string>()

export interface ReferenceImageItem {
  id: string
  number: number
  label: string
  file: File
}

function getReferenceFileId(file: File): string {
  const existing = referenceFileIds.get(file)
  if (existing) return existing
  const id = `reference-file-${++referenceFileSequence}`
  referenceFileIds.set(file, id)
  return id
}

export function getReferenceImageItems(files: File[]): ReferenceImageItem[] {
  return files.map((file, index) => ({
    id: getReferenceFileId(file),
    number: index + 1,
    label: `图片${index + 1}`,
    file,
  }))
}

export function validateVideoImageReferences(prompt: string, imageCount: number): string[] {
  if (prompt.includes('@图片已删除')) {
    return ['提示词引用的图片已被删除，请重新选择图片引用']
  }
  if (INVALID_IMAGE_REFERENCE.test(prompt)) {
    return ['图片引用格式不合法，请使用 @图片1、@图片2 等正整数编号']
  }

  const missing = new Set<number>()
  for (const match of prompt.matchAll(VALID_IMAGE_REFERENCE)) {
    const number = Number(match[1])
    if (number > imageCount) missing.add(number)
  }
  return [...missing].map(
    (number) => `提示词引用了不存在的 @图片${number}，当前只有 ${imageCount} 张参考图`,
  )
}

export function normalizeVideoImageReferences(prompt: string): string {
  return prompt.replace(VALID_IMAGE_REFERENCE, (_, number: string) => `图片${number}`)
}

export function remapVideoImageReferences(
  prompt: string,
  previousFiles: File[],
  nextFiles: File[],
): string {
  // File 对象身份代表用户当前选择的具体素材，同名或同内容的新文件不能冒充已删除素材。
  return prompt.replace(VALID_IMAGE_REFERENCE, (mention, number: string) => {
    const previousFile = previousFiles[Number(number) - 1]
    if (!previousFile) return mention
    const nextIndex = nextFiles.indexOf(previousFile)
    return nextIndex >= 0 ? `@图片${nextIndex + 1}` : '@图片已删除'
  })
}

export function insertVideoImageReference(
  value: string,
  replaceStart: number,
  replaceEnd: number,
  imageNumber: number,
): { value: string; cursor: number } {
  const mention = `@图片${imageNumber}`
  const nextValue = `${value.slice(0, replaceStart)}${mention}${value.slice(replaceEnd)}`
  return {
    value: nextValue,
    cursor: replaceStart + mention.length,
  }
}

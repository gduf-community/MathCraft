/** 上传专属校验：限制格式与空文件，文件大小上限由服务端判定。 */
export const DOCUMENT_ACCEPT = '.pdf,.docx,.xlsx,.md,.markdown,.txt'

const FORMATS = new Map([
  ['pdf', 'PDF'], ['docx', 'DOCX'], ['xlsx', 'XLSX'], ['md', 'MD'], ['markdown', 'MD'], ['txt', 'TXT'],
])

export function documentFormat(name: string): string | undefined {
  const extension = /\.([^.]+)$/.exec(name)?.[1].toLowerCase()
  return extension ? FORMATS.get(extension) : undefined
}

export function uploadFileKey(file: File): string {
  return JSON.stringify([file.name, file.size, file.lastModified])
}

export function validateUploadFiles(incoming: Iterable<File>, existing: Iterable<File> = []) {
  const seen = new Set(Array.from(existing, uploadFileKey))
  const files: File[] = []
  const errors: string[] = []
  for (const file of incoming) {
    if (!documentFormat(file.name)) {
      errors.push(`「${file.name}」格式不支持，请选择 PDF / DOCX / XLSX / MD / markdown / TXT`)
    } else if (file.size === 0) {
      errors.push(`「${file.name}」是空文件，请选择有内容的文件`)
    } else if (seen.has(uploadFileKey(file))) {
      errors.push(`「${file.name}」重复（名称、大小和修改时间相同）`)
    } else {
      seen.add(uploadFileKey(file))
      files.push(file)
    }
  }
  return { files, errors }
}

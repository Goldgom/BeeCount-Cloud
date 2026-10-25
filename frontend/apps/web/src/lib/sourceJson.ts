// This accepts normalized JSON only; it intentionally does not guess CLI-specific schemas.
export const MAX_SOURCE_JSON_BYTES = 2 * 1024 * 1024
export function parseSourceJson(text: string): Record<string, unknown> {
  let value: unknown
  try { value = JSON.parse(text.replace(/^\uFEFF/, '')) } catch { throw new Error('文件不是有效的 JSON。请先将 CLI 输出转换为标准 schema。') }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('JSON 顶层必须是对象；请参考服务端 schema。')
  return value as Record<string, unknown>
}

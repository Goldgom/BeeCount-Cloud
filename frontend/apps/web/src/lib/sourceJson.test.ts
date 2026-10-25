import { describe, expect, it } from 'vitest'
import { parseSourceJson } from './sourceJson'

describe('normalized source JSON', () => {
  it('preserves decimal strings without floating point conversion', () => {
    expect(parseSourceJson('{"balance":"0.000000000000000001"}').balance).toBe('0.000000000000000001')
  })
  it('supports UTF-8 BOM exports', () => {
    expect(parseSourceJson('\uFEFF{"version":1}')).toEqual({ version: 1 })
  })
  it.each(['null', '[]', '1', '"text"', 'shell output'])('rejects non-object or malformed input %s', (text) => {
    expect(() => parseSourceJson(text)).toThrow()
  })
})

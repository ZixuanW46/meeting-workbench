import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// jsdom 不算样式，这里直接锁样式表里的关键约定：
// micro-interaction 存在、且整体尊重 prefers-reduced-motion。
// vitest 的 cwd 固定在 apps/web（package.json 所在目录）。
const css = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf8')

describe('样式约定', () => {
  it('列表行有 hover 反馈与行尾箭头 micro-interaction', () => {
    expect(css).toContain('.list-row:hover')
    expect(css).toContain('.list-row-chevron')
  })

  it('按钮有按压反馈', () => {
    expect(css).toContain('.btn:active')
  })

  it('进度条当前步骤有轻微动效', () => {
    expect(css).toContain('.progress-seg.current')
  })

  it('动效尊重 prefers-reduced-motion', () => {
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
  })

  it('键盘可达：保留 focus-visible 态', () => {
    expect(css).toContain(':focus-visible')
  })
})

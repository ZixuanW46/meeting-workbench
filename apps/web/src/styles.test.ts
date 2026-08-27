import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// jsdom 不算样式，这里直接锁样式表里的关键约定：
// Linear 近黑画布令牌（docs/LINEAR-DESIGN.md）、micro-interaction 存在、
// 且整体尊重 prefers-reduced-motion。
// vitest 的 cwd 固定在 apps/web（package.json 所在目录）。
const css = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf8')

describe('Linear 近黑画布令牌', () => {
  it('画布是 #010102，而不是纯黑 #000000', () => {
    expect(css).toContain('--canvas: #010102')
    expect(css).not.toContain('--canvas: #000000')
  })

  it('四级表面阶梯与发丝线取自 DESIGN.md', () => {
    expect(css).toContain('--surface-1: #0f1011')
    expect(css).toContain('--surface-2: #141516')
    expect(css).toContain('--surface-3: #18191a')
    expect(css).toContain('--surface-4: #191a1b')
    expect(css).toContain('--hairline: #23252a')
    expect(css).toContain('--hairline-strong: #34343a')
  })

  it('文字梯度取自 DESIGN.md', () => {
    expect(css).toContain('--ink: #f7f8f8')
    expect(css).toContain('--ink-muted: #d0d6e0')
    expect(css).toContain('--ink-subtle: #8a8f98')
    expect(css).toContain('--ink-tertiary: #62666d')
  })

  it('薰衣草主色与 hover / focus 变体取自 DESIGN.md', () => {
    expect(css).toContain('--primary: #5e6ad2')
    expect(css).toContain('--primary-hover: #828fff')
    expect(css).toContain('--primary-focus: #5e69d1')
  })

  it('强调 CTA 是 Linear button-inverse 白底，不用薰衣草填充', () => {
    expect(css).toContain('--inverse-canvas: #ffffff')
    const btnPrimary = /\.btn-primary\s*\{[^}]*\}/.exec(css)?.[0] ?? ''
    expect(btnPrimary).toContain('background: var(--inverse-canvas)')
    expect(btnPrimary).not.toContain('var(--primary)')
  })

  it('品牌标记已移除：CSS 里不再有 .sidebar-brand-mark', () => {
    expect(css).not.toContain('.sidebar-brand-mark')
  })

  it('成功色只有 #27a644 一个营销色', () => {
    expect(css).toContain('--success: #27a644')
  })

  it('暗面不投影：没有 drop shadow，只有顶边微光与焦点环', () => {
    expect(css).not.toContain('--shadow-sm')
    const shadows = css.match(/box-shadow:[^;]+;/g) ?? []
    for (const s of shadows) {
      expect(s).toMatch(/inset|0 0 0 2px|var\(--edge-highlight\)/)
    }
  })
})

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

  it('键盘可达：focus-visible 环用半透明 primary-focus', () => {
    expect(css).toContain(':focus-visible')
    expect(css).toContain('rgba(94, 105, 209, 0.5)')
  })

  it('原生控件走深色（color-scheme）', () => {
    expect(css).toContain('color-scheme: dark')
  })
})

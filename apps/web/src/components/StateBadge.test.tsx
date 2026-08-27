import { render } from '@testing-library/react'
import { StateBadge } from './StateBadge'

// 锁住状态色板：进行中 / 停点 / 完成 / 出错 / 静默 五档，不许退化成裸文本
const TONE_CASES: Array<[state: string, tone: string, label: string]> = [
  ['PROCESSING', 'badge-active', '处理中'],
  ['AWAITING_SPEAKER_REVIEW', 'badge-attention', '待确认说话人'],
  ['PARTIAL_READY', 'badge-attention', '转写完成，纪要待生成'],
  ['READY', 'badge-done', '已完成'],
  ['FAILED', 'badge-error', '处理失败'],
  ['CANCELED', 'badge-muted', '已取消'],
]

describe('状态徽标', () => {
  it.each(TONE_CASES)('%s → %s（%s）', (state, tone, label) => {
    const { container } = render(<StateBadge state={state} />)
    const badge = container.querySelector('.badge')
    expect(badge).not.toBeNull()
    expect(badge).toHaveClass(tone)
    expect(badge).toHaveTextContent(label)
    // 色点只做装饰，不承担语义
    expect(badge?.querySelector('.badge-dot')).toHaveAttribute('aria-hidden', 'true')
  })
})

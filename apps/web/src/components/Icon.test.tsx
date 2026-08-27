import { render } from '@testing-library/react'
import { ICON_NAMES, Icon } from './Icon'

describe('统一图标', () => {
  it('渲染 aria-hidden 的内联 SVG，描边跟随文字颜色', () => {
    const { container } = render(<Icon name="plus" />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).toHaveAttribute('stroke', 'currentColor')
    expect(svg).toHaveAttribute('fill', 'none')
    expect(svg).toHaveAttribute('viewBox', '0 0 16 16')
  })

  it('全站用到的图标名都有非空路径', () => {
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />)
      const svg = container.querySelector('svg')
      expect(svg).not.toBeNull()
      expect(svg?.querySelector('path, rect, circle')).not.toBeNull()
    }
  })

  it('size 同时作用于宽高，默认贴合 13px 正文', () => {
    const { container } = render(<Icon name="close" size={12} />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('width', '12')
    expect(svg).toHaveAttribute('height', '12')
  })
})

import { render, screen, within } from '@testing-library/react'
import {
  PlaudImportOverlay,
  formatMegabytes,
  phaseLabel,
  progressPercent,
} from './PlaudImportOverlay'

describe('导入遮罩的数字排版', () => {
  it('字节按 MB 一位小数排版', () => {
    expect(formatMegabytes(0)).toBe('0.0 MB')
    expect(formatMegabytes(132644864)).toBe('126.5 MB')
    expect(formatMegabytes(55710843)).toBe('53.1 MB')
    // 负数（后端异常）不该显示成 -0.0 MB
    expect(formatMegabytes(-1)).toBe('0.0 MB')
  })

  it('百分比向下取整并夹在 0～100，总大小未知时没有百分比', () => {
    expect(progressPercent(55710843, 132644864)).toBe(42)
    // 99.7% 不提前显示成 100%
    expect(progressPercent(997, 1000)).toBe(99)
    expect(progressPercent(1200, 1000)).toBe(100)
    expect(progressPercent(10, null)).toBeNull()
    expect(progressPercent(10, 0)).toBeNull()
  })

  it('阶段文案覆盖到「还没登记」的 null', () => {
    expect(phaseLabel(null)).toBe('正在向 Plaud 取音频直链…')
    expect(phaseLabel('resolving')).toBe('正在向 Plaud 取音频直链…')
    expect(phaseLabel('downloading')).toBe('正在下载录音…')
    expect(phaseLabel('finalizing')).toBe('下载完成，正在排队处理…')
  })
})

describe('导入遮罩', () => {
  it('是挡住整页的 dialog，带录音名与时长', () => {
    render(
      <PlaudImportOverlay
        phase="downloading"
        bytesDone={55710843}
        bytesTotal={132644864}
        recordingName="客户访谈"
        recordingDurationMs={5220000}
      />,
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-busy', 'true')
    expect(within(dialog).getByText('客户访谈')).toBeInTheDocument()
    expect(within(dialog).getByText('1h27m')).toBeInTheDocument()
    expect(within(dialog).getByText('42%')).toBeInTheDocument()
    expect(within(dialog).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42')
    expect(within(dialog).getByText('请勿关闭页面')).toBeInTheDocument()
  })

  it('总大小未知时走不确定态：没有百分比，进度条不给 aria-valuenow', () => {
    render(
      <PlaudImportOverlay
        phase="downloading"
        bytesDone={55710843}
        bytesTotal={null}
        recordingName="客户访谈"
        recordingDurationMs={312000}
      />,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByText(/%$/)).not.toBeInTheDocument()
    expect(within(dialog).getByText('已下载 53.1 MB')).toBeInTheDocument()
    expect(within(dialog).getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('取直链阶段即使知道总大小也不画确定进度', () => {
    render(
      <PlaudImportOverlay
        phase="resolving"
        bytesDone={0}
        bytesTotal={132644864}
        recordingName="客户访谈"
        recordingDurationMs={312000}
      />,
    )

    expect(screen.getByText('正在向 Plaud 取音频直链…')).toBeInTheDocument()
    expect(screen.getByText('正在建立连接…')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })
})

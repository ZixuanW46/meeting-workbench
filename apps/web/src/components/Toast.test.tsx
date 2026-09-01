import { act, fireEvent, render, screen } from '@testing-library/react'
import { Toaster, toast } from './Toast'

describe('Toast', () => {
  it('toast() 在右下角出现，点击立即关闭', async () => {
    render(<Toaster />)

    act(() => {
      toast('已删除「产品周会」')
    })
    const item = await screen.findByText('已删除「产品周会」')
    expect(item).toBeInTheDocument()

    fireEvent.click(item)
    expect(screen.queryByText('已删除「产品周会」')).not.toBeInTheDocument()
  })

  it('成功 4 秒后自动消失，错误样式带 error 类', async () => {
    vi.useFakeTimers()
    try {
      render(<Toaster />)
      act(() => {
        toast('标题已更新')
        toast('处理中的会议不能删除', 'error')
      })
      expect(screen.getByText('标题已更新')).toBeInTheDocument()
      expect(screen.getByText('处理中的会议不能删除')).toHaveClass('toast-error')

      act(() => {
        vi.advanceTimersByTime(4500)
      })
      expect(screen.queryByText('标题已更新')).not.toBeInTheDocument()
      // 错误 6s 存活，此刻还在
      expect(screen.getByText('处理中的会议不能删除')).toBeInTheDocument()

      act(() => {
        vi.advanceTimersByTime(2000)
      })
      expect(
        screen.queryByText('处理中的会议不能删除'),
      ).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})

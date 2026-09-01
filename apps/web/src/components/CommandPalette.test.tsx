import { fireEvent, render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { CommandPalette } from './CommandPalette'

const MEETINGS = [
  {
    id: 'm1',
    title: '产品周会',
    state: 'READY',
    expected_speakers: null,
    hotwords: [],
    created_at: '2026-08-26T08:00:00Z',
    speakers: ['Will'],
    unknown_speaker_count: 0,
  },
  {
    id: 'm2',
    title: '架构评审',
    state: 'READY',
    expected_speakers: null,
    hotwords: [],
    created_at: '2026-08-25T02:30:00Z',
    speakers: [],
    unknown_speaker_count: 0,
  },
]

describe('命令面板', () => {
  beforeEach(() => {
    window.location.hash = ''
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })),
    )
  })

  it('打开后列出会议与导航项，选中会议即跳转并关闭', async () => {
    const onClose = vi.fn()
    render(<CommandPalette open onClose={onClose} />)

    expect(screen.getByPlaceholderText('搜索会议，或输入命令…')).toBeInTheDocument()
    expect(await screen.findByText('架构评审')).toBeInTheDocument()
    expect(screen.getByText('新建会议')).toBeInTheDocument()

    fireEvent.click(screen.getByText('架构评审'))
    expect(window.location.hash).toBe('#/meetings/m2')
    expect(onClose).toHaveBeenCalled()
  })

  it('输入关键词过滤会议', async () => {
    render(<CommandPalette open onClose={() => {}} />)

    await screen.findByText('架构评审')
    fireEvent.change(screen.getByPlaceholderText('搜索会议，或输入命令…'), {
      target: { value: '架构' },
    })

    expect(screen.getByText('架构评审')).toBeInTheDocument()
    expect(screen.queryByText('产品周会')).not.toBeInTheDocument()
  })
})

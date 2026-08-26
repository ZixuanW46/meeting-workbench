import { render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { MeetingListPage } from './MeetingListPage'

const MEETINGS = [
  {
    id: 'm1',
    title: '产品周会',
    state: 'AWAITING_SPEAKER_REVIEW',
    expected_speakers: 4,
    hotwords: ['声纹'],
    created_at: '2026-08-26T08:00:00Z',
  },
  {
    id: 'm2',
    title: '架构评审',
    state: 'READY',
    expected_speakers: null,
    hotwords: [],
    created_at: '2026-08-25T02:30:00Z',
  },
]

describe('会议列表页', () => {
  it('从 /api/meetings 渲染真数据', async () => {
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })),
    )

    render(<MeetingListPage />)

    expect(await screen.findByText('产品周会')).toBeInTheDocument()
    expect(screen.getByText('架构评审')).toBeInTheDocument()
    // 状态渲染成中文标签，不是裸枚举值
    expect(screen.getByText('待确认说话人')).toBeInTheDocument()
    expect(screen.getByText('已完成')).toBeInTheDocument()
    // 行链接指向工作台
    expect(screen.getByRole('link', { name: /产品周会/ })).toHaveAttribute(
      'href',
      '#/meetings/m1',
    )
  })

  it('空列表保留空态', async () => {
    server.use(http.get('/api/meetings', () => HttpResponse.json({ items: [] })))

    render(<MeetingListPage />)

    expect(await screen.findByText('还没有会议')).toBeInTheDocument()
  })
})

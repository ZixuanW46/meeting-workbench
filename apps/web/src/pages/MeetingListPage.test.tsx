import { render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { makeDoctorReport } from '../test/doctor'
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

  it('doctor 未就绪时两条横幅同时出现，不挡列表与新建', async () => {
    sessionStorage.clear()
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })),
      http.get('/api/doctor', () =>
        HttpResponse.json(
          makeDoctorReport({
            ffmpeg: false,
            transcription_ready: false,
            minutes_ready: false,
          }),
        ),
      ),
    )

    render(<MeetingListPage />)

    expect(await screen.findByText(/转写暂不可用/)).toBeInTheDocument()
    expect(await screen.findByText(/纪要暂不可用/)).toBeInTheDocument()
    // 列表与新建入口照常可用
    expect(await screen.findByText('产品周会')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '新建会议' })).toBeInTheDocument()
  })

  it('空列表保留空态', async () => {
    server.use(http.get('/api/meetings', () => HttpResponse.json({ items: [] })))

    render(<MeetingListPage />)

    expect(await screen.findByText('还没有会议')).toBeInTheDocument()
  })
})

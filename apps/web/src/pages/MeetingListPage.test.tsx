import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { makeDoctorReport } from '../test/doctor'
import { server } from '../test/server'
import { MeetingListPage } from './MeetingListPage'

const MEETINGS = [
  {
    id: 'm1',
    title: '产品周会',
    state: 'AWAITING_SPEAKER_REVIEW',
    expected_speakers: null,
    hotwords: ['声纹'],
    created_at: '2026-08-26T08:00:00Z',
    speakers: [],
    unknown_speaker_count: 0,
  },
  {
    id: 'm2',
    title: '架构评审',
    state: 'READY',
    expected_speakers: null,
    hotwords: [],
    created_at: '2026-08-25T02:30:00Z',
    speakers: ['Will', 'Leo', 'Eddie'],
    unknown_speaker_count: 1,
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

  it('列表行两行式：标题下带人数与时间；副标题显示统计', async () => {
    server.use(http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })))

    render(<MeetingListPage />)

    await screen.findByText('产品周会')
    // 副标题：总数 + 等确认数
    expect(screen.getByText('2 场会议 · 1 场等你确认说话人')).toBeInTheDocument()
    // 行内第二行：确认后的实际参会人数 + 创建时间（未确认的行只有时间）
    expect(screen.getByText(/参会 4 人 · /)).toBeInTheDocument()
    const rows = screen.getAllByRole('link', { name: /评审|周会/ })
    expect(rows).toHaveLength(2)
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

  it('列表行带 hover 行尾箭头（图标装饰，不进可访问名）', async () => {
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })),
    )

    const { container } = render(<MeetingListPage />)

    await screen.findByText('产品周会')
    const rows = container.querySelectorAll('.list-row')
    expect(rows).toHaveLength(2)
    for (const row of rows) {
      const chevron = row.querySelector('.list-row-chevron')
      expect(chevron).not.toBeNull()
      expect(chevron).toHaveAttribute('aria-hidden', 'true')
    }
    // 行链接可访问名仍是标题本身
    expect(screen.getByRole('link', { name: /产品周会/ })).toBeInTheDocument()
  })

  it('删除会议：两段式确认后行消失，取消则不发请求', async () => {
    let deleteCalled = 0
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })),
      http.delete('/api/meetings/m2', () => {
        deleteCalled += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<MeetingListPage />)
    await screen.findByText('架构评审')

    // 第一次点删除只进入确认态，不发请求
    fireEvent.click(screen.getByRole('button', { name: '删除会议 架构评审' }))
    expect(deleteCalled).toBe(0)

    // 取消退回
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('button', { name: '确认删除' })).not.toBeInTheDocument()

    // 再来一次并确认
    fireEvent.click(screen.getByRole('button', { name: '删除会议 架构评审' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(deleteCalled).toBe(1))
    await waitFor(() =>
      expect(screen.queryByText('架构评审')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('产品周会')).toBeInTheDocument()
  })

  it('删除处理中的会议：后端 409 时展示错误且行保留', async () => {
    server.use(
      http.get('/api/meetings', () => HttpResponse.json({ items: MEETINGS })),
      http.delete('/api/meetings/m1', () =>
        HttpResponse.json({ detail: '处理中的会议不能删除' }, { status: 409 }),
      ),
    )

    render(<MeetingListPage />)
    await screen.findByText('产品周会')

    fireEvent.click(screen.getByRole('button', { name: '删除会议 产品周会' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    expect(await screen.findByText('处理中的会议不能删除')).toBeInTheDocument()
    expect(screen.getByText('产品周会')).toBeInTheDocument()
  })

  it('空列表保留空态', async () => {
    server.use(http.get('/api/meetings', () => HttpResponse.json({ items: [] })))

    render(<MeetingListPage />)

    expect(await screen.findByText('还没有会议')).toBeInTheDocument()
  })
})

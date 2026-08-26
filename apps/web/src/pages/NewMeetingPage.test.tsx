import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { NewMeetingPage } from './NewMeetingPage'

describe('新建会议表单', () => {
  beforeEach(() => {
    window.location.hash = '#/new'
  })

  it('标题为空时拦截提交并提示', async () => {
    let posted = false
    server.use(
      http.post('/api/meetings', () => {
        posted = true
        return HttpResponse.json({}, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    expect(await screen.findByText('请输入标题')).toBeInTheDocument()
    expect(posted).toBe(false)
  })

  it('人数默认「不确定」，热词回车成标签，提交后跳转工作台', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          {
            id: 'm-new',
            title: '周会',
            state: 'DRAFT',
            expected_speakers: null,
            hotwords: ['声纹', 'MLX'],
            created_at: '2026-08-26T08:00:00Z',
          },
          { status: 201 },
        )
      }),
    )

    render(<NewMeetingPage />)

    // 人数可选「不确定」，且是默认值
    const speakers = screen.getByLabelText('预计人数') as HTMLSelectElement
    expect(
      Array.from(speakers.options).some((o) => o.text === '不确定'),
    ).toBe(true)
    expect(speakers.selectedOptions[0].text).toBe('不确定')

    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '周会' } })

    const hotwordInput = screen.getByLabelText('本场热词')
    fireEvent.change(hotwordInput, { target: { value: '声纹' } })
    fireEvent.keyDown(hotwordInput, { key: 'Enter' })
    fireEvent.change(hotwordInput, { target: { value: 'MLX' } })
    fireEvent.keyDown(hotwordInput, { key: 'Enter' })
    // 两个标签已渲染
    expect(screen.getByText('声纹')).toBeInTheDocument()
    expect(screen.getByText('MLX')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({
      title: '周会',
      expected_speakers: null,
      hotwords: ['声纹', 'MLX'],
    })
    await waitFor(() => expect(window.location.hash).toBe('#/meetings/m-new'))
  })

  it('选具体人数时提交数字', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          {
            id: 'm-4',
            title: '四人会',
            state: 'DRAFT',
            expected_speakers: 4,
            hotwords: [],
            created_at: '2026-08-26T08:00:00Z',
          },
          { status: 201 },
        )
      }),
    )

    render(<NewMeetingPage />)
    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '四人会' } })
    fireEvent.change(screen.getByLabelText('预计人数'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect((body as Record<string, unknown> | null)?.expected_speakers).toBe(4)
  })
})

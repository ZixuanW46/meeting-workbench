import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server, useProjects } from '../test/server'
import { NewMeetingPage } from './NewMeetingPage'

describe('新建会议表单', () => {
  beforeEach(() => {
    window.location.hash = '#/new'
  })

  it('标题可留空：提交不带 title，由后端按文件名与纪要自动命名', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ hotwords: [], meeting_date: localToday(), language: 'zh' })
    expect(screen.queryByText('请输入标题')).not.toBeInTheDocument()
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
      hotwords: ['声纹', 'MLX'],
      meeting_date: localToday(),
      language: 'zh',
    })
    await waitFor(() => expect(window.location.hash).toBe('#/meetings/m-new'))
  })

  it('语言默认中文，选 English 后随表单提交', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)

    // 默认选中「中文」
    expect(screen.getByRole('button', { name: '中文' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: 'English' })).not.toHaveClass('active')

    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(screen.getByRole('button', { name: 'English' })).toHaveClass('active')

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ language: 'en' })
  })

  it('会议日期默认今天，可改成录音当天并随表单提交', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)

    const dateInput = screen.getByLabelText('会议日期') as HTMLInputElement
    expect(dateInput.value).toBe(localToday())
    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '周会' } })
    fireEvent.change(dateInput, { target: { value: '2026-08-30' } })
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ meeting_date: '2026-08-30' })
  })
  it('选中项目后随表单提交 project_id；不选则整个字段不出现', async () => {
    let body: Record<string, unknown> | null = null
    useProjects()
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    const select = await screen.findByLabelText('项目')
    expect((select as HTMLSelectElement).value).toBe('')
    await screen.findByRole('option', { name: '声纹研究' })

    fireEvent.change(select, { target: { value: 'p2' } })
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ project_id: 'p2' })
  })

  it('选「新建项目…」就地创建，创建完自动选中并随表单提交', async () => {
    let posted: { name: string } | null = null
    let body: Record<string, unknown> | null = null
    useProjects()
    server.use(
      http.post('/api/projects', async ({ request }) => {
        posted = (await request.json()) as { name: string }
        return HttpResponse.json(
          {
            id: 'p9',
            name: posted.name,
            created_at: '2026-09-03T00:00:00Z',
            meeting_count: 0,
            hotword_count: 0,
          },
          { status: 201 },
        )
      }),
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    const select = await screen.findByLabelText('项目')
    await screen.findByRole('option', { name: '声纹研究' })

    fireEvent.change(select, { target: { value: '__new__' } })
    const nameInput = screen.getByLabelText('新项目名字')
    fireEvent.change(nameInput, { target: { value: '内网基建' } })
    fireEvent.keyDown(nameInput, { key: 'Enter' })

    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('p9'))
    expect(posted).toEqual({ name: '内网基建' })
    expect(screen.queryByLabelText('新项目名字')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ project_id: 'p9' })
  })
})

function localToday(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

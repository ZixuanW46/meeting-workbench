import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import type { Project } from '../api/client'
import { InlineProjectCreate } from './InlineProjectCreate'

const CREATED = {
  id: 'p9',
  name: '内网基建',
  created_at: '2026-09-03T00:00:00Z',
  meeting_count: 0,
  hotword_count: 0,
}

/** 注册一个记录请求体的 POST /api/projects */
function useCreateProject(): { body: { name: string } | null } {
  const captured: { body: { name: string } | null } = { body: null }
  server.use(
    http.post('/api/projects', async ({ request }) => {
      captured.body = (await request.json()) as { name: string }
      return HttpResponse.json({ ...CREATED, name: captured.body.name }, { status: 201 })
    }),
  )
  return captured
}

describe('InlineProjectCreate', () => {
  it('平时只是一个按钮，点开才出输入框', () => {
    render(<InlineProjectCreate onCreated={() => {}} />)

    expect(screen.queryByLabelText('新项目名字')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))

    expect(screen.getByLabelText('新项目名字')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建项目' })).toBeDisabled()
  })

  it('回车创建：POST 后回调新项目并收起', async () => {
    const captured = useCreateProject()
    const created: Project[] = []

    render(<InlineProjectCreate onCreated={(project) => created.push(project)} />)
    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))

    const input = screen.getByLabelText('新项目名字')
    fireEvent.change(input, { target: { value: '  内网基建  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(created).toHaveLength(1))
    // 名字两端空白在提交前就被裁掉
    expect(captured.body).toEqual({ name: '内网基建' })
    expect(created[0]?.id).toBe('p9')
    // 收起回按钮态
    expect(screen.queryByLabelText('新项目名字')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '新建项目' })).toBeInTheDocument()
  })

  it('点「创建」按钮同样能创建', async () => {
    const captured = useCreateProject()
    const created: Project[] = []

    render(<InlineProjectCreate onCreated={(project) => created.push(project)} />)
    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
    fireEvent.change(screen.getByLabelText('新项目名字'), { target: { value: '声纹研究' } })
    fireEvent.click(screen.getByRole('button', { name: '创建项目' }))

    await waitFor(() => expect(created).toHaveLength(1))
    expect(captured.body).toEqual({ name: '声纹研究' })
  })

  it('Esc 与「取消」都收起且不发请求', async () => {
    let posted = 0
    server.use(
      http.post('/api/projects', () => {
        posted += 1
        return HttpResponse.json(CREATED, { status: 201 })
      }),
    )
    render(<InlineProjectCreate onCreated={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
    const input = screen.getByLabelText('新项目名字')
    fireEvent.change(input, { target: { value: '临时' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByLabelText('新项目名字')).not.toBeInTheDocument()

    // 再次点开：上一轮输入不残留
    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
    expect((screen.getByLabelText('新项目名字') as HTMLInputElement).value).toBe('')

    fireEvent.click(screen.getByRole('button', { name: '取消新建项目' }))
    expect(screen.queryByLabelText('新项目名字')).not.toBeInTheDocument()
    expect(posted).toBe(0)
  })

  it('重名 409：行内显示后端 detail，输入框留着不收起', async () => {
    server.use(
      http.post('/api/projects', () =>
        HttpResponse.json({ detail: '项目「会议工作台」已存在' }, { status: 409 }),
      ),
    )
    const created: Project[] = []

    render(<InlineProjectCreate onCreated={(project) => created.push(project)} />)
    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
    const input = screen.getByLabelText('新项目名字')
    fireEvent.change(input, { target: { value: '会议工作台' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByRole('alert')).toHaveTextContent('项目「会议工作台」已存在')
    expect(created).toHaveLength(0)
    expect(screen.getByLabelText('新项目名字')).toBeInTheDocument()
  })

  it('创建中禁用输入与两个按钮', async () => {
    // 把 resolve 存进对象里：直接用 let 会被 TS 收窄成 null
    const gate: { release: (() => void) | null } = { release: null }
    server.use(
      http.post('/api/projects', async () => {
        await new Promise<void>((resolve) => {
          gate.release = resolve
        })
        return HttpResponse.json(CREATED, { status: 201 })
      }),
    )

    render(<InlineProjectCreate onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
    const input = screen.getByLabelText('新项目名字')
    fireEvent.change(input, { target: { value: '内网基建' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(input).toBeDisabled())
    expect(screen.getByRole('button', { name: '创建项目' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '取消新建项目' })).toBeDisabled()

    await waitFor(() => expect(gate.release).not.toBeNull())
    gate.release?.()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '新建项目' })).toBeInTheDocument(),
    )
  })

  it('compact 形态渲染成一颗 pill', () => {
    render(<InlineProjectCreate compact onCreated={() => {}} />)
    expect(screen.getByRole('button', { name: '新建项目' })).toHaveClass('pill-add')
  })
})

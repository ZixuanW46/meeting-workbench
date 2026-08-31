import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { HotwordsPage } from './HotwordsPage'

const ITEMS = [
  { id: 'h1', word: 'Qwen3', note: '本机转写模型' },
  { id: 'h2', word: '声纹库', note: null },
]

describe('词库页', () => {
  it('列出全局词语并说明快照语义', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
    )

    render(<HotwordsPage />)

    expect(await screen.findByText('Qwen3')).toBeInTheDocument()
    expect(screen.getByText('声纹库')).toBeInTheDocument()
    expect(screen.getByText(/只影响之后开始转写的会议/)).toBeInTheDocument()
  })

  it('回车添加词语并出现在列表；重复词把 409 详情展示出来', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.post('/api/hotwords', async ({ request }) => {
        const body = (await request.json()) as { word: string }
        if (body.word === '已存在') {
          return HttpResponse.json({ detail: '词语已存在' }, { status: 409 })
        }
        return HttpResponse.json({ id: 'h9', word: body.word }, { status: 201 })
      }),
    )

    render(<HotwordsPage />)
    const input = await screen.findByLabelText('添加词语')

    fireEvent.change(input, { target: { value: 'meeting-workbench' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText('meeting-workbench')).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe('')

    fireEvent.change(input, { target: { value: '已存在' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText(/词语已存在/)).toBeInTheDocument()
  })

  it('删除词语后从列表移除', async () => {
    let deleted: string | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.delete('/api/hotwords/:id', ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    fireEvent.click(screen.getByRole('button', { name: '删除词语 Qwen3' }))

    await waitFor(() => {
      expect(screen.queryByText('Qwen3')).not.toBeInTheDocument()
    })
    expect(deleted).toBe('h1')
    expect(screen.getByText('声纹库')).toBeInTheDocument()
  })

  it('词库为空时给出引导文案', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
    )

    render(<HotwordsPage />)

    expect(await screen.findByText('词库是空的')).toBeInTheDocument()
  })

  it('展示词语注解；无注解的词提供添加入口', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
    )

    render(<HotwordsPage />)

    expect(await screen.findByText('本机转写模型')).toBeInTheDocument()
    // 两行都有注解编辑入口（有注解的显示「编辑注解」，没有的显示「添加注解」）。
    expect(
      screen.getByRole('button', { name: '编辑注解 Qwen3' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '添加注解 声纹库' }),
    ).toBeInTheDocument()
  })

  it('就地编辑注解并保存：PATCH 生效、列表即时更新', async () => {
    let patched: { id: string; note: unknown } | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.patch('/api/hotwords/:id', async ({ params, request }) => {
        const body = (await request.json()) as { note: string | null }
        patched = { id: String(params.id), note: body.note }
        return HttpResponse.json({ id: params.id, word: 'Qwen3', note: body.note })
      }),
    )

    render(<HotwordsPage />)
    await screen.findByText('本机转写模型')

    fireEvent.click(screen.getByRole('button', { name: '编辑注解 Qwen3' }))
    const noteInput = screen.getByLabelText('注解内容 Qwen3')
    expect((noteInput as HTMLInputElement).value).toBe('本机转写模型')

    fireEvent.change(noteInput, { target: { value: '本机 ASR 模型（Qwen3-ASR）' } })
    fireEvent.keyDown(noteInput, { key: 'Enter' })

    expect(
      await screen.findByText('本机 ASR 模型（Qwen3-ASR）'),
    ).toBeInTheDocument()
    expect(patched).toEqual({ id: 'h1', note: '本机 ASR 模型（Qwen3-ASR）' })
  })

  it('添加词语可以顺带填注解，一起提交', async () => {
    let posted: { word: string; note?: string | null } | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.post('/api/hotwords', async ({ request }) => {
        posted = (await request.json()) as { word: string; note?: string | null }
        return HttpResponse.json(
          { id: 'h9', word: posted.word, note: posted.note ?? null },
          { status: 201 },
        )
      }),
    )

    render(<HotwordsPage />)
    const wordInput = await screen.findByLabelText('添加词语')
    const noteInput = screen.getByLabelText('注解（选填，喂给纪要 LLM）')

    fireEvent.change(wordInput, { target: { value: 'CUES' } })
    fireEvent.change(noteInput, { target: { value: '剑桥工程社团简称' } })
    fireEvent.keyDown(noteInput, { key: 'Enter' })

    expect(await screen.findByText('CUES')).toBeInTheDocument()
    expect(screen.getByText('剑桥工程社团简称')).toBeInTheDocument()
    expect(posted).toEqual({ word: 'CUES', note: '剑桥工程社团简称' })
  })
})

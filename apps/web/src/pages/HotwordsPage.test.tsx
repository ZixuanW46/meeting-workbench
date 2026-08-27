import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { HotwordsPage } from './HotwordsPage'

const ITEMS = [
  { id: 'h1', word: 'Qwen3' },
  { id: 'h2', word: '声纹库' },
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
})

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { VoiceprintsPage } from './VoiceprintsPage'

const ITEMS = [
  {
    id: 'vp1',
    person_id: 'p1',
    display_name: '王芳',
    created_at: '2026-08-27T10:00:00Z',
    source_meeting_title: '产品周会',
    snippet_text: '先对齐今天要定的两件事。',
    has_clip: true,
  },
  {
    id: 'vp2',
    person_id: 'p1',
    display_name: '王芳',
    created_at: '2026-08-28T02:00:00Z',
    source_meeting_title: '用户访谈',
    snippet_text: '咱们先聊聊当时为什么选了年付。',
    has_clip: false,
  },
  {
    id: 'vp3',
    person_id: 'p2',
    display_name: '李雷',
    created_at: null,
    source_meeting_title: null,
    snippet_text: '',
    has_clip: false,
  },
]

describe('声纹库页', () => {
  it('按人分组展示多条模板：摘录、来源会议、试听按钮', async () => {
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: ITEMS })),
    )

    render(<VoiceprintsPage />)

    await screen.findByText('王芳')
    // 王芳一组两条模板，李雷一组一条
    expect(screen.getByText('2 条模板')).toBeInTheDocument()
    expect(screen.getByText('1 条模板')).toBeInTheDocument()
    expect(screen.getByText('先对齐今天要定的两件事。')).toBeInTheDocument()
    expect(screen.getByText(/产品周会/)).toBeInTheDocument()
    // 有切片的模板给试听按钮；没有的标注「无试听切片」
    expect(
      screen.getByRole('button', { name: '试听 王芳 的模板' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/无试听切片/)).toHaveLength(2)
    // 早期入库（无时间）与来源缺失的兜底文案
    expect(screen.getByText(/来源会议已不存在 · 早期入库/)).toBeInTheDocument()
    expect(screen.getByText('（无转写摘录）')).toBeInTheDocument()
  })

  it('删除单条模板：该行消失，同组其余模板保留', async () => {
    let deleted: string | null = null
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: ITEMS })),
      http.delete('/api/voiceprints/:id', ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<VoiceprintsPage />)
    await screen.findByText('王芳')

    const buttons = screen.getAllByRole('button', {
      name: '删除 王芳 的这条声纹模板',
    })
    expect(buttons).toHaveLength(2)
    fireEvent.click(buttons[0])

    await waitFor(() => {
      expect(deleted).toBe('vp1')
    })
    await waitFor(() => {
      expect(
        screen.queryByText('先对齐今天要定的两件事。'),
      ).not.toBeInTheDocument()
    })
    expect(
      screen.getByText('咱们先聊聊当时为什么选了年付。'),
    ).toBeInTheDocument()
  })

  it('声纹库为空时保留空态引导', async () => {
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: [] })),
    )

    render(<VoiceprintsPage />)

    expect(await screen.findByText('声纹库是空的')).toBeInTheDocument()
  })

  it('点试听不因环境不支持音频而崩溃', async () => {
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: ITEMS })),
    )

    render(<VoiceprintsPage />)
    await screen.findByText('王芳')

    fireEvent.click(screen.getByRole('button', { name: '试听 王芳 的模板' }))

    // jsdom 无真实音频栈：只要不崩、按钮仍在（试听或暂停态均可）即可
    expect(
      screen.getByRole('button', { name: /王芳 的模板/ }),
    ).toBeInTheDocument()
  })
})

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { VoiceprintsPage } from './VoiceprintsPage'

const VOICEPRINTS = [
  { id: 'vp1', person_id: 'p1', display_name: '王芳' },
  { id: 'vp2', person_id: 'p2', display_name: '李雷' },
]

describe('声纹库页', () => {
  it('从 /api/voiceprints 渲染人员列表', async () => {
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: VOICEPRINTS })),
    )

    render(<VoiceprintsPage />)

    expect(await screen.findByText('王芳')).toBeInTheDocument()
    expect(screen.getByText('李雷')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '删除 王芳 的声纹' }),
    ).toBeInTheDocument()
  })

  it('空库保留空态', async () => {
    server.use(http.get('/api/voiceprints', () => HttpResponse.json({ items: [] })))

    render(<VoiceprintsPage />)

    expect(await screen.findByText('声纹库是空的')).toBeInTheDocument()
  })

  it('删除成功后该行消失', async () => {
    let deleted = false
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: VOICEPRINTS })),
      http.delete('/api/voiceprints/vp1', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<VoiceprintsPage />)
    fireEvent.click(await screen.findByRole('button', { name: '删除 王芳 的声纹' }))

    await waitFor(() => {
      expect(screen.queryByText('王芳')).not.toBeInTheDocument()
    })
    expect(deleted).toBe(true)
    expect(screen.getByText('李雷')).toBeInTheDocument()
  })

  it('删除失败展示后端错误并保留该行', async () => {
    server.use(
      http.get('/api/voiceprints', () => HttpResponse.json({ items: VOICEPRINTS })),
      http.delete('/api/voiceprints/vp1', () =>
        HttpResponse.json({ detail: '声纹不存在' }, { status: 404 }),
      ),
    )

    render(<VoiceprintsPage />)
    fireEvent.click(await screen.findByRole('button', { name: '删除 王芳 的声纹' }))

    expect(await screen.findByText('声纹不存在')).toBeInTheDocument()
    expect(screen.getByText('王芳')).toBeInTheDocument()
  })
})

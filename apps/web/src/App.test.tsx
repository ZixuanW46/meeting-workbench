import { fireEvent, render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import App from './App'
import { server, useProjects } from './test/server'

describe('App 壳', () => {
  it('默认路由渲染会议列表', async () => {
    window.location.hash = ''
    server.use(http.get('/api/meetings', () => HttpResponse.json({ items: [] })))

    render(<App />)

    expect(screen.getByText('会议工作台')).toBeInTheDocument()
    expect(await screen.findByText('还没有会议')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '新建会议' })).toHaveAttribute(
      'href',
      '#/new',
    )
    expect(screen.getByRole('link', { name: '声纹库' })).toHaveAttribute(
      'href',
      '#/voiceprints',
    )
  })

  it('#/voiceprints 渲染声纹库页', async () => {
    window.location.hash = '#/voiceprints'
    server.use(http.get('/api/voiceprints', () => HttpResponse.json({ items: [] })))

    render(<App />)

    expect(await screen.findByText('声纹库是空的')).toBeInTheDocument()
    window.location.hash = ''
  })

  it('#/hotwords?project=<id> 直达词库并选中该项目', async () => {
    window.location.hash = '#/hotwords?project=p2'
    useProjects()
    server.use(
      http.get('/api/projects/p2/hotwords', () =>
        HttpResponse.json({ items: [{ id: 'ph2', word: '说话人簇', note: null }] }),
      ),
    )

    render(<App />)

    expect(await screen.findByText('说话人簇')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '声纹研究' })).toBeInTheDocument()
    // 带查询串也算词库路由：侧栏照旧高亮
    expect(screen.getByRole('link', { name: '词库' })).toHaveClass('active')
    window.location.hash = ''
  })

  it('⌘K 呼出命令面板，Esc 关闭', async () => {
    window.location.hash = ''
    server.use(http.get('/api/meetings', () => HttpResponse.json({ items: [] })))

    render(<App />)
    await screen.findByText('还没有会议')

    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(
      await screen.findByPlaceholderText('搜索会议，或输入命令…'),
    ).toBeInTheDocument()

    fireEvent.keyDown(
      screen.getByPlaceholderText('搜索会议，或输入命令…'),
      { key: 'Escape' },
    )
    expect(
      screen.queryByPlaceholderText('搜索会议，或输入命令…'),
    ).not.toBeInTheDocument()
  })
})

import { render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import App from './App'
import { server } from './test/server'

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
  })
})

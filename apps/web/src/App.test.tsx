import { render, screen } from '@testing-library/react'
import App from './App'

describe('App 壳', () => {
  it('渲染会议列表占位页', () => {
    render(<App />)
    expect(screen.getByText('会议工作台')).toBeInTheDocument()
    expect(screen.getByText('会议列表')).toBeInTheDocument()
    expect(screen.getByText('还没有会议')).toBeInTheDocument()
  })
})

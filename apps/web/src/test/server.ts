import { setupServer } from 'msw/node'

// 各测试文件通过 server.use(...) 注册自己的 handler。
export const server = setupServer()

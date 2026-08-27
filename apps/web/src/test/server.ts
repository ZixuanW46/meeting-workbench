import { HttpResponse, http } from 'msw'
import { setupServer } from 'msw/node'
import { makeDoctorReport } from './doctor'

// 各测试文件通过 server.use(...) 注册自己的 handler。
// doctor 默认全就绪：页面测试无需关心就绪横幅即可保持绿。
export const server = setupServer(
  http.get('/api/doctor', () => HttpResponse.json(makeDoctorReport())),
)

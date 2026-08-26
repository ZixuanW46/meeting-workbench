import { ConfigProvider, Layout, Typography } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { MeetingListPage } from './pages/MeetingListPage'

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <Layout style={{ minHeight: '100vh' }}>
        <Layout.Header>
          <Typography.Title level={4} style={{ color: '#fff', margin: 0, lineHeight: '64px' }}>
            会议工作台
          </Typography.Title>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          <MeetingListPage />
        </Layout.Content>
      </Layout>
    </ConfigProvider>
  )
}

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { FrappeProvider } from 'frappe-react-sdk'
import './index.css'
import Layout from './components/Layout.jsx'
import { ToastProvider } from './components/Toast.jsx'
import Overview from './pages/Overview.jsx'
import Messages from './pages/Messages.jsx'
import Rules from './pages/Rules.jsx'
import Destinations from './pages/Destinations.jsx'
import Users from './pages/Users.jsx'
import InstallGuide from './pages/InstallGuide.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter basename={import.meta.env.MODE === 'demo' ? import.meta.env.BASE_URL : '/teams-notify'}>
      <FrappeProvider enableSocket={false} swrConfig={{ revalidateOnFocus: true }}>
        <ToastProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="messages" element={<Messages />} />
              <Route path="rules" element={<Rules />} />
              <Route path="destinations" element={<Destinations />} />
              <Route path="users" element={<Users />} />
              <Route path="install" element={<InstallGuide />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </ToastProvider>
      </FrappeProvider>
    </BrowserRouter>
  </StrictMode>
)

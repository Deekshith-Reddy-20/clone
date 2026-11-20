import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { AppShell } from './components/app/AppShell'
import { ProtectedRoute } from './components/ProtectedRoute'
import { BillingPage } from './pages/app/BillingPage'
import { CallDetailPage } from './pages/app/CallDetailPage'
import { CampaignsPage } from './pages/app/CampaignsPage'
import { ConversationsPage } from './pages/app/ConversationsPage'
import { DevelopersPage } from './pages/app/DevelopersPage'
import { HireEmployeePage } from './pages/app/HireEmployeePage'
import { IncomingCallsPage } from './pages/app/IncomingCallsPage'
import { InstantLeadsPage } from './pages/app/InstantLeadsPage'
import { LeadsPage } from './pages/app/LeadsPage'
import { NumbersPage } from './pages/app/NumbersPage'
import { PerformancePage } from './pages/app/PerformancePage'
import { SettingsPage } from './pages/app/SettingsPage'
import { TeamPage } from './pages/app/TeamPage'
import { BookingRequestsPage } from './pages/app/BookingRequestsPage'
import { VoiceAgentsPage } from './pages/app/VoiceAgentsPage'
import { WelcomePage } from './pages/WelcomePage'

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<WelcomePage />} />
          <Route path="/sign-in" element={<Navigate to="/" replace />} />
          <Route path="/create-account" element={<Navigate to="/" replace />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/app" element={<AppShell />}>
              <Route index element={<HireEmployeePage />} />
              <Route path="team" element={<TeamPage />} />
              <Route path="team/:employeeId" element={<TeamPage />} />
              <Route path="leads" element={<LeadsPage />} />
              <Route path="booking-requests" element={<BookingRequestsPage />} />
              <Route path="conversations" element={<ConversationsPage />} />
              <Route path="conversations/:callId" element={<CallDetailPage />} />
              <Route path="performance" element={<PerformancePage />} />
              <Route path="campaigns" element={<CampaignsPage />} />
              <Route path="instant" element={<InstantLeadsPage />} />
              <Route path="voice-agents" element={<VoiceAgentsPage />} />
              <Route path="incoming" element={<IncomingCallsPage />} />
              <Route path="numbers" element={<NumbersPage />} />
              <Route path="billing" element={<BillingPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="developers" element={<DevelopersPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
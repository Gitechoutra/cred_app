import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import AppShell from '../components/layout/AppShell';
import ErrorBoundary from '../components/ErrorBoundary';
import { Spinner } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useProfile } from '../hooks/useProfile';

/* Auth */
import Splash from '../pages/auth/Splash';
import PhoneEntry from '../pages/auth/PhoneEntry';
import OtpVerify from '../pages/auth/OtpVerify';
import ProfileSetup from '../pages/auth/ProfileSetup';
import MpinSetup from '../pages/auth/MpinSetup';
import MpinLogin from '../pages/auth/MpinLogin';
import AdminLogin from '../pages/auth/AdminLogin';

/* Member */
import Home from '../pages/user/Home';
import Cards from '../pages/user/Cards';
import CardDetail from '../pages/user/CardDetail';
import AddCard from '../pages/user/AddCard';
import BankAccounts from '../pages/user/BankAccounts';
import AddBankAccount from '../pages/user/AddBankAccount';
import Transfer from '../pages/user/Transfer';
import TransferStatus from '../pages/user/TransferStatus';
import EmiList from '../pages/user/EmiList';
import EmiDetail from '../pages/user/EmiDetail';
import AddEmi from '../pages/user/AddEmi';
import EmiPay from '../pages/user/EmiPay';
import MandateSetup from '../pages/user/MandateSetup';
import Transactions from '../pages/user/Transactions';
import TransactionDetail from '../pages/user/TransactionDetail';
import Notifications from '../pages/user/Notifications';
import Profile from '../pages/user/Profile';
import Kyc from '../pages/user/Kyc';
import Security from '../pages/user/Security';
import Support from '../pages/user/Support';

/* Admin */
import AdminLayout from '../pages/admin/AdminLayout';
import AdminDashboard from '../pages/admin/AdminDashboard';
import AdminUsers from '../pages/admin/AdminUsers';
import AdminKycQueue from '../pages/admin/AdminKycQueue';
import AdminTransfers from '../pages/admin/AdminTransfers';
import AdminReconciliation from '../pages/admin/AdminReconciliation';
import AdminSettings from '../pages/admin/AdminSettings';

function FullPageLoader() {
  return (
    <div className="grid min-h-screen place-items-center bg-canvas">
      <Spinner className="h-6 w-6 text-mint-600" />
    </div>
  );
}

/**
 * Gate for signed-in routes.
 *
 * Onboarding is finished here rather than in each page: a user who verified an
 * OTP but never set a name or an MPIN is pushed through those steps before they
 * can reach anything else. Otherwise a half-registered account lands on a
 * dashboard that cannot work.
 */
function RequireAuth({ children }) {
  const { isAuthenticated } = useAuth();
  const { profile, loading, needsProfile, needsMpin } = useProfile();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/" replace state={{ from: location.pathname }} />;
  }

  if (loading || !profile) return <FullPageLoader />;

  if (needsProfile && location.pathname !== '/onboarding/profile') {
    return <Navigate to="/onboarding/profile" replace />;
  }

  if (!needsProfile && needsMpin && location.pathname !== '/onboarding/mpin') {
    return <Navigate to="/onboarding/mpin" replace />;
  }

  return children;
}

function RequireAdmin({ children }) {
  const { isAuthenticated } = useAuth();
  const { profile, loading, isAdmin } = useProfile();

  if (!isAuthenticated) return <Navigate to="/" replace />;
  if (loading || !profile) return <FullPageLoader />;
  if (!isAdmin) return <Navigate to="/home" replace />;

  return children;
}

/** Signed-in users should not see the sign-in screens again. */
function RedirectIfAuthed({ children }) {
  const { isAuthenticated } = useAuth();
  const { profile, loading, isAdmin } = useProfile();

  if (!isAuthenticated) return children;
  if (loading) return <FullPageLoader />;
  if (profile) return <Navigate to={isAdmin ? '/admin' : '/home'} replace />;

  return children;
}

/** Member routes render inside the shell with its bottom navigation. */
function Shell({ children }) {
  return (
    <AppShell>
      <ErrorBoundary>{children}</ErrorBoundary>
    </AppShell>
  );
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/" element={<RedirectIfAuthed><Splash /></RedirectIfAuthed>} />
      <Route path="/signin" element={<RedirectIfAuthed><PhoneEntry /></RedirectIfAuthed>} />
      <Route path="/signin/otp" element={<RedirectIfAuthed><OtpVerify /></RedirectIfAuthed>} />
      <Route path="/signin/mpin" element={<RedirectIfAuthed><MpinLogin /></RedirectIfAuthed>} />
      <Route path="/admin/login" element={<RedirectIfAuthed><AdminLogin /></RedirectIfAuthed>} />

      {/* Onboarding - authenticated but incomplete */}
      <Route
        path="/onboarding/profile"
        element={<RequireAuth><ProfileSetup /></RequireAuth>}
      />
      <Route
        path="/onboarding/mpin"
        element={<RequireAuth><MpinSetup /></RequireAuth>}
      />

      {/* Member */}
      <Route path="/home" element={<RequireAuth><Shell><Home /></Shell></RequireAuth>} />
      <Route path="/cards" element={<RequireAuth><Shell><Cards /></Shell></RequireAuth>} />
      <Route path="/cards/add" element={<RequireAuth><Shell><AddCard /></Shell></RequireAuth>} />
      <Route path="/cards/:cardId" element={<RequireAuth><Shell><CardDetail /></Shell></RequireAuth>} />

      <Route path="/banks" element={<RequireAuth><Shell><BankAccounts /></Shell></RequireAuth>} />
      <Route path="/banks/add" element={<RequireAuth><Shell><AddBankAccount /></Shell></RequireAuth>} />

      <Route path="/transfer" element={<RequireAuth><Shell><Transfer /></Shell></RequireAuth>} />
      <Route path="/transfer/status/:transferId" element={<RequireAuth><Shell><TransferStatus /></Shell></RequireAuth>} />

      <Route path="/emi" element={<RequireAuth><Shell><EmiList /></Shell></RequireAuth>} />
      <Route path="/emi/add" element={<RequireAuth><Shell><AddEmi /></Shell></RequireAuth>} />
      <Route path="/emi/:emiId" element={<RequireAuth><Shell><EmiDetail /></Shell></RequireAuth>} />
      <Route path="/emi/:emiId/pay" element={<RequireAuth><Shell><EmiPay /></Shell></RequireAuth>} />
      <Route path="/emi/:emiId/autopay" element={<RequireAuth><Shell><MandateSetup /></Shell></RequireAuth>} />

      <Route path="/transactions" element={<RequireAuth><Shell><Transactions /></Shell></RequireAuth>} />
      <Route path="/transactions/:transactionId" element={<RequireAuth><Shell><TransactionDetail /></Shell></RequireAuth>} />
      <Route path="/notifications" element={<RequireAuth><Shell><Notifications /></Shell></RequireAuth>} />

      <Route path="/profile" element={<RequireAuth><Shell><Profile /></Shell></RequireAuth>} />
      <Route path="/kyc" element={<RequireAuth><Shell><Kyc /></Shell></RequireAuth>} />
      <Route path="/security" element={<RequireAuth><Shell><Security /></Shell></RequireAuth>} />
      <Route path="/support" element={<RequireAuth><Shell><Support /></Shell></RequireAuth>} />

      {/* Admin console */}
      <Route path="/admin" element={<RequireAdmin><AdminLayout /></RequireAdmin>}>
        <Route index element={<AdminDashboard />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="kyc" element={<AdminKycQueue />} />
        <Route path="transfers" element={<AdminTransfers />} />
        <Route path="reconciliation" element={<AdminReconciliation />} />
        <Route path="settings" element={<AdminSettings />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

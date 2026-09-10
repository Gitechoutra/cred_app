import { Navigate, Route, Routes } from 'react-router-dom';

import SandboxChallenge from '../pages/user/transfer/SandboxChallenge';
import TransferAmount from '../pages/user/transfer/TransferAmount';
import TransferStatus from '../pages/user/transfer/TransferStatus';

/**
 * Route table.
 *
 * Only the Cashfree transfer path is wired up so far; the auth, dashboard,
 * cards, EMI and admin surfaces from version1.md section 7.1 slot in alongside
 * it as they are built.
 *
 * Two status routes on purpose. `/transfer/status?transfer_id=…` is the shape
 * Cashfree redirects to after the 3DS challenge (the backend appends the id to
 * CASHFREE_RETURN_URL), and `/transfer/:transferId/status` is the shape an
 * in-app link uses. Both render the same screen.
 */
export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/transfer" replace />} />

      <Route path="/transfer" element={<TransferAmount />} />
      <Route path="/transfer/status" element={<TransferStatus />} />
      <Route path="/transfer/:transferId/status" element={<TransferStatus />} />

      {/* Reachable only while the backend runs on simulated adapters. */}
      <Route path="/transfer/sandbox/:transferId" element={<SandboxChallenge />} />

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function NotFound() {
  return (
    <div className="mx-auto max-w-lg p-6 text-center">
      <h1 className="text-2xl font-semibold text-ink">Page not found</h1>
      <p className="mt-2 text-sm text-slate">
        The page you are looking for does not exist.
      </p>
    </div>
  );
}

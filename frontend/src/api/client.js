/**
 * API client.
 *
 * One place that knows how to talk to the CashU backend, so no component ever
 * assembles a fetch by hand. Three things it handles that a bare fetch does not:
 *
 * 1. **Token refresh.** Access tokens live 15 minutes (PRD FR-001). On a 401 the
 *    client refreshes once and replays the request, so a user mid-transfer is
 *    never bounced to the login screen by an expiry they cannot see.
 *
 * 2. **Single-flight refresh.** Several requests hitting 401 together must not
 *    each burn a refresh token - the server rotates it on every use, so the
 *    second would fail and sign the user out. They queue behind the first.
 *
 * 3. **Idempotency keys.** Every money-moving call carries one, generated here
 *    so a component cannot forget and cause a double charge.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || '/v1';

const ACCESS_KEY = 'cashu.access';
const REFRESH_KEY = 'cashu.refresh';
const DEVICE_KEY = 'cashu.device';

export const apiEmitter = new EventTarget();

/* ── Token storage ──────────────────────────────────────────────────────── */

export const tokens = {
  get access() {
    try {
      return localStorage.getItem(ACCESS_KEY);
    } catch {
      return null;
    }
  },
  get refresh() {
    try {
      return localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  },
  set({ access_token, refresh_token }) {
    try {
      if (access_token) localStorage.setItem(ACCESS_KEY, access_token);
      if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token);
    } catch {
      /* Private browsing. The session simply will not survive a reload. */
    }
  },
  clear() {
    try {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
    } catch {
      /* ignore */
    }
  },
};

/**
 * A stable per-browser device id.
 *
 * PRD FR-001 binds sessions to a device so a stolen token cannot be replayed
 * from elsewhere, and a previously unseen device triggers a security alert.
 */
function deviceId() {
  try {
    let id = localStorage.getItem(DEVICE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(DEVICE_KEY, id);
    }
    return id;
  } catch {
    return 'ephemeral-device';
  }
}

export function newIdempotencyKey() {
  return crypto.randomUUID().replace(/-/g, '');
}

/* ── Errors ─────────────────────────────────────────────────────────────── */

export class ApiError extends Error {
  constructor({ code, message, details, recovery, status }) {
    super(message || 'Something went wrong.');
    this.code = code;
    this.details = details;
    this.recovery = recovery;
    this.status = status;
  }
}

/* ── Refresh, single-flight ─────────────────────────────────────────────── */

let refreshInFlight = null;

async function refreshTokens() {
  if (refreshInFlight) return refreshInFlight;

  const token = tokens.refresh;
  if (!token) return Promise.resolve(false);

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${BASE}/authentication/refresh`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'X-Device-UUID': deviceId(),
        },
      });

      if (!response.ok) {
        tokens.clear();
        return false;
      }

      const body = await response.json();
      tokens.set(body.data);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/* ── Core request ───────────────────────────────────────────────────────── */

async function request(path, { method = 'GET', body, form, idempotent, retry = true, background = false } = {}) {
  const headers = { 'X-Device-UUID': deviceId() };

  const access = tokens.access;
  if (access) headers.Authorization = `Bearer ${access}`;
  if (idempotent) headers['X-Idempotency-Key'] = idempotent;

  if (!background) apiEmitter.dispatchEvent(new Event('start'));

  let payload;
  if (form) {
    // Let the browser set the multipart boundary; setting Content-Type by hand
    // omits it and the server cannot parse the body.
    payload = form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  } catch {
    if (!background) apiEmitter.dispatchEvent(new Event('error'));
    throw new ApiError({
      code: 'NETWORK_ERROR',
      message: 'We could not reach CashU. Check your connection and try again.',
      status: 0,
    });
  }

  // Expired access token: refresh once, then replay exactly this request.
  if (response.status === 401 && retry && tokens.refresh) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      return request(path, { method, body, form, idempotent, retry: false });
    }
  }

  let parsed = null;
  try {
    parsed = await response.json();
  } catch {
    /* 204, or a body that is not JSON. */
  }

  if (!response.ok || (parsed && parsed.success === false)) {
    const error = (parsed && parsed.error) || {};
    if (!background) apiEmitter.dispatchEvent(new Event('error'));
    throw new ApiError({
      code: error.code || `HTTP_${response.status}`,
      message: error.message || 'Something went wrong. Please try again.',
      details: error.details,
      recovery: error.recovery,
      status: response.status,
    });
  }

  if (!background) apiEmitter.dispatchEvent(new Event('end'));
  return parsed;
}


/**
 * Fetch a protected binary (a KYC document) as an object URL.
 *
 * `<img src>` cannot send an Authorization header, so a token-protected image
 * has to be fetched like any other API call and wrapped in a blob URL. The
 * caller owns the returned URL and must revokeObjectURL it on unmount, or the
 * blob leaks for the life of the tab.
 */
export async function fetchBlobUrl(path) {
  const headers = { 'X-Device-UUID': deviceId() };
  const access = tokens.access;
  if (access) headers.Authorization = `Bearer ${access}`;

  let response = await fetch(`${BASE}${path}`, { headers });

  // Same single-flight refresh the JSON path uses.
  if (response.status === 401 && tokens.refresh) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      headers.Authorization = `Bearer ${tokens.access}`;
      response = await fetch(`${BASE}${path}`, { headers });
    }
  }

  if (!response.ok) {
    let message = 'Could not load this document.';
    try {
      const body = await response.json();
      message = body?.error?.message || message;
    } catch {
      /* binary endpoints may not return JSON on failure */
    }
    throw new ApiError({ code: 'DOCUMENT_ERROR', message, status: response.status });
  }

  const blob = await response.blob();

  // The MIME type comes back too: the KYC viewer has to know whether it is
  // about to show a PNG or a PDF, and an object URL does not carry that.
  return { url: URL.createObjectURL(blob), type: blob.type };
}

/* ── Verbs ──────────────────────────────────────────────────────────────── */

export const api = {
  get: (path) => request(path),
  post: (path, body, options = {}) => request(path, { method: 'POST', body, ...options }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  del: (path) => request(path, { method: 'DELETE' }),
  upload: (path, form) => request(path, { method: 'POST', form }),

  /** POST that moves money - always carries a fresh idempotency key. */
  pay: (path, body) => request(path, {
    method: 'POST',
    body,
    idempotent: newIdempotencyKey(),
  }),
};

/* ── Endpoints ──────────────────────────────────────────────────────────── */

export const endpoints = {
  auth: {
    sendOtp: (phone) => api.post('/authentication/otp/send', { phone }),
    verifyOtp: (phone, otp, deviceName) =>
      api.post('/authentication/otp/verify', { phone, otp, device_name: deviceName }),
    register: (data) => api.post('/authentication/register', data),
    setMpin: (mpin) => api.post('/authentication/mpin/set', { mpin }),
    loginMpin: (phone, mpin) => api.post('/authentication/mpin/verify', { phone, mpin }),
    logout: () => api.post('/authentication/logout'),
    sessions: () => api.get('/authentication/sessions'),
    revokeAll: () => api.del('/authentication/sessions'),
  },
  me: {
    get: () => api.get('/users/me'),
    update: (data) => api.patch('/users/me', data),
    security: (data) => api.patch('/users/me/security', data),
    loginHistory: () => api.get('/users/me/login-history'),
    exportData: () => api.post('/users/me/export'),
  },
  kyc: {
    status: () => api.get('/kyc/status'),
    submit: (form) => api.upload('/kyc/submit', form),
  },
  dashboard: {
    get: () => api.get('/dashboard'),
    activity: () => api.get('/dashboard/activity'),
  },
  cards: {
    list: () => api.get('/cards'),
    get: (id) => api.get(`/cards/${id}`),
    lookupBin: (bin) => api.get(`/cards/networks/lookup/${bin}`),
    // Predefined dummy cards. 404s when test mode is off, which is how the UI
    // knows not to show the picker at all.
    testCards: () => api.get('/cards/test-cards'),
    link: (data) => api.post('/cards', data),
    update: (id, data) => api.patch(`/cards/${id}`, data),
    unlink: (id) => api.del(`/cards/${id}`),
    payBill: (id, data) => api.post(`/cards/${id}/pay-bill`, data),
  },
  qrPayments: {
    // The scanned string is validated server-side; the client never parses it.
    decode: (payload) => api.post('/qr-payments/decode', { payload }),
    pay: (data) => api.pay('/qr-payments', data),
    get: (id) => api.get(`/qr-payments/${id}`),
    verify: (id, data) => api.post(`/qr-payments/${id}/verify`, data),
    cancel: (id) => api.post(`/qr-payments/${id}/cancel`),
    list: () => api.get('/qr-payments'),
  },
  banks: {
    list: () => api.get('/bank-accounts'),
    get: (id) => api.get(`/bank-accounts/${id}`),
    add: (data) => api.post('/bank-accounts', data),
    remove: (id) => api.del(`/bank-accounts/${id}`),
    verify: (id) => api.post(`/bank-accounts/${id}/verify`),
    setPrimary: (id) => api.post(`/bank-accounts/${id}/primary`),
    lookupIfsc: (ifsc) => api.get(`/bank-accounts/ifsc/${ifsc}`),
    lookupAccount: (data) => api.post('/bank-accounts/lookup-account', data),
  },
  transfers: {
    // Which instruments may fund a transfer, and why UPI is not among them.
    methods: () => api.get('/transfers/methods'),
    // Hands Razorpay Checkout's signed payload to the server, which verifies
    // the signature and re-reads the charge before dispatching the payout.
    verify: (id, data) => api.post(`/transfers/${id}/verify`, data),
    quote: (amount) => api.post('/transfers/quote', { amount }),
    limits: () => api.get('/transfers/limits'),
    list: (page = 1) => api.get(`/transfers?page=${page}`),
    get: (id) => api.get(`/transfers/${id}`),
    initiate: (data) => api.pay('/transfers', data),
    confirm: (id) => api.post(`/transfers/${id}/confirm`),
    receipt: (id) => api.get(`/transfers/${id}/receipt`),
  },
  emi: {
    providers: () => api.get('/emi/providers'),
    list: () => api.get('/emi'),
    get: (id) => api.get(`/emi/${id}`),
    lookup: (data) => api.post('/emi/lookup', data),
    add: (data) => api.post('/emi', data),
    update: (id, data) => api.patch(`/emi/${id}`, data),
    remove: (id) => api.del(`/emi/${id}`),
  },
  emiPayments: {
    methods: () => api.get('/emi-payments/methods'),
    list: (emiId) => api.get(`/emi-payments${emiId ? `?emi_id=${emiId}` : ''}`),
    pay: (data) => api.pay('/emi-payments', data),
    confirm: (id) => api.post(`/emi-payments/${id}/confirm`),
    // Hands Razorpay Checkout's signed handler payload to the server, which
    // verifies the signature and then re-reads the payment from Razorpay. The
    // browser never decides whether a payment succeeded.
    verify: (id, data) => api.post(`/emi-payments/${id}/verify`, data),
    cancel: (id) => api.post(`/emi-payments/${id}/cancel`),
    get: (id) => api.get(`/emi-payments/${id}`),
    receipt: (id) => api.get(`/emi-payments/${id}/receipt`),
  },
  mandates: {
    list: () => api.get('/mandates'),
    preview: (emiId) => api.get(`/mandates/preview?emi_id=${emiId}`),
    get: (id) => api.get(`/mandates/${id}`),
    create: (data) => api.post('/mandates', data),
    activate: (id) => api.post(`/mandates/${id}/activate`),
    pause: (id, reason) => api.post(`/mandates/${id}/pause`, { reason }),
    resume: (id) => api.post(`/mandates/${id}/resume`),
    cancel: (id) => api.del(`/mandates/${id}`),
  },
  transactions: {
    list: (params = '') => api.get(`/transactions${params}`),
    get: (id) => api.get(`/transactions/${id}`),
    summary: () => api.get('/transactions/summary'),
  },
  notifications: {
    list: (page = 1) => api.get(`/notifications?page=${page}`),
    markRead: (id) => api.post(`/notifications/${id}/read`),
    markAllRead: () => api.post('/notifications/read-all'),
    preferences: () => api.get('/notifications/preferences'),
    updatePreferences: (data) => api.patch('/notifications/preferences', data),
  },
  support: {
    tickets: () => api.get('/support/tickets'),
    get: (id) => api.get(`/support/tickets/${id}`),
    create: (data) => api.post('/support/tickets', data),
    reply: (id, message) => api.post(`/support/tickets/${id}/reply`, { message }),
  },
  admin: {
    dashboard: () => api.get('/admin/dashboard'),
    users: (params = '') => api.get(`/admin/users${params}`),
    user: (id) => api.get(`/admin/users/${id}`),
    freeze: (id, reason) => api.post(`/admin/users/${id}/freeze`, { reason }),
    unfreeze: (id, reason) => api.post(`/admin/users/${id}/unfreeze`, { reason }),
    kycQueue: () => api.get('/admin/kyc/queue'),
    reviewKyc: (id, data) => api.post(`/admin/kyc/${id}/review`, data),
    kycDocumentUrl: (id, slot) => fetchBlobUrl(`/admin/kyc/${id}/document/${slot}`),
    transfers: (params = '') => api.get(`/admin/transfers${params}`),
    stuckTransfers: () => api.get('/admin/transfers/stuck'),
    retryPayout: (id, reason) => api.post(`/admin/transfers/${id}/retry-payout`, { reason }),
    reverse: (id, reason) => api.post(`/admin/transfers/${id}/reverse`, { reason }),
    reconciliation: () => api.get('/admin/reconciliation'),
    selfAudit: () => api.post('/admin/reconciliation/self-audit'),
    settings: () => api.get('/admin/settings'),
    updateSetting: (key, value) => api.patch(`/admin/settings/${key}`, { value }),
    flags: () => api.get('/admin/feature-flags'),
    updateFlag: (key, data) => api.patch(`/admin/feature-flags/${key}`, data),
    auditLogs: (params = '') => api.get(`/admin/audit-logs${params}`),
  },
};

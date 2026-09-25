import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './app/App';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import { ProfileProvider } from './hooks/useProfile';
import { NavHistoryProvider } from './hooks/useNavHistory';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <NavHistoryProvider>
      <AuthProvider>
        <ProfileProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </ProfileProvider>
      </AuthProvider>
      </NavHistoryProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

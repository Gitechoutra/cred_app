import React, { createContext, useContext, useEffect, useState } from 'react';
import { Loader3D } from '../components/ui/Loader3D';
import { apiEmitter } from '../api/client';

const LoadingContext = createContext();

export function LoadingProvider({ children }) {
  const [requestCount, setRequestCount] = useState(0);

  useEffect(() => {
    const handleLoadingStart = () => setRequestCount(c => c + 1);
    const handleLoadingEnd = () => setRequestCount(c => Math.max(0, c - 1));

    apiEmitter.addEventListener('start', handleLoadingStart);
    apiEmitter.addEventListener('end', handleLoadingEnd);
    apiEmitter.addEventListener('error', handleLoadingEnd);

    return () => {
      apiEmitter.removeEventListener('start', handleLoadingStart);
      apiEmitter.removeEventListener('end', handleLoadingEnd);
      apiEmitter.removeEventListener('error', handleLoadingEnd);
    };
  }, []);

  const showGlobalLoader = requestCount > 0;

  return (
    <LoadingContext.Provider value={{}}>
      {children}
      {showGlobalLoader && <Loader3D fullScreen />}
    </LoadingContext.Provider>
  );
}

export function useGlobalLoading() {
  const context = useContext(LoadingContext);
  if (!context) {
    throw new Error('useGlobalLoading must be used within a LoadingProvider');
  }
  return context;
}

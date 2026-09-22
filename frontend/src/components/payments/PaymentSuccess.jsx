import React, { useEffect, useState } from 'react';
import { cx } from '../ui';

export function PaymentSuccess({ onComplete }) {
  const [stage, setStage] = useState('start'); // start -> expanding -> check -> done

  useEffect(() => {
    // Sequence the animation
    const t1 = setTimeout(() => setStage('expanding'), 100);
    const t2 = setTimeout(() => setStage('check'), 600);
    const t3 = setTimeout(() => {
      setStage('done');
      if (onComplete) onComplete();
    }, 2500);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [onComplete]);

  return (
    <div className={cx(
      "fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-canvas transition-opacity duration-500",
      stage === 'done' ? "opacity-0 pointer-events-none" : "opacity-100"
    )}>
      
      {/* Background radial glow */}
      <div className={cx(
        "absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-mint-500/20 via-canvas to-canvas transition-opacity duration-700",
        stage === 'start' ? "opacity-0" : "opacity-100"
      )} />

      {/* Circle animation container */}
      <div className="relative flex h-32 w-32 items-center justify-center">
        {/* Expanding rings */}
        <div className={cx(
          "absolute inset-0 rounded-full border-2 border-mint-400 transition-all duration-1000 ease-out",
          stage === 'start' ? "scale-50 opacity-0" : "scale-[2] opacity-0"
        )} />
        <div className={cx(
          "absolute inset-0 rounded-full border-2 border-mint-500 transition-all duration-1000 delay-150 ease-out",
          stage === 'start' ? "scale-50 opacity-0" : "scale-[1.5] opacity-0"
        )} />
        
        {/* Main Circle */}
        <div className={cx(
          "absolute inset-0 rounded-full bg-gradient-to-tr from-mint-600 to-mint-400 shadow-[0_0_40px_rgba(0,245,184,0.4)] transition-all duration-500 ease-out flex items-center justify-center",
          stage === 'start' ? "scale-0 opacity-0" : "scale-100 opacity-100"
        )}>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={cx(
              "h-12 w-12 text-white transition-all duration-500 delay-200",
              stage === 'check' || stage === 'done' ? "scale-100 opacity-100" : "scale-50 opacity-0"
            )}
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
      </div>

      <div className={cx(
        "mt-8 flex flex-col items-center transition-all duration-500 delay-300",
        stage === 'check' || stage === 'done' ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0"
      )}>
        <h2 className="text-2xl font-bold text-ink tracking-tight">Payment Successful</h2>
        <p className="mt-2 text-sm text-slate">Your bill has been cleared.</p>
      </div>

    </div>
  );
}

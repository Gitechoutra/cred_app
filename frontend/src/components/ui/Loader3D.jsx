import React from 'react';
import './Loader3D.css';
import { cx } from './index';

const SIZES = {
  small: '24px',
  medium: '48px',
  large: '80px',
  fullScreen: '100px',
};

export function Loader3D({ fullScreen = false, size = 'medium', className = '' }) {
  const cssVars = {
    '--loader-size': fullScreen ? SIZES.fullScreen : SIZES[size] || SIZES.medium,
  };

  const loaderCore = (
    <div className="loader-coin-wrapper" style={cssVars}>
      <div className="loader-orbit" />
      <div className="loader-coin">
        <span className="loader-u">U</span>
      </div>
    </div>
  );

  if (fullScreen) {
    return (
      <div className="loader-3d-full">
        <div className="loader-3d-container">
          {loaderCore}
        </div>
        <div className="loader-text-wrapper">
          <div className="loader-text-main">Just a moment...</div>
          <div className="loader-text-sub">We're processing your request.</div>
          <div className="loader-dots">
            <div className="loader-dot"></div>
            <div className="loader-dot"></div>
            <div className="loader-dot"></div>
            <div className="loader-dot"></div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={cx('loader-3d-inline loader-3d-container', className)}>
      {loaderCore}
    </div>
  );
}

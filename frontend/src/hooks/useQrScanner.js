import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Camera QR scanning, with no library.
 *
 * Uses the browser's native BarcodeDetector, which Chrome and Edge ship on
 * desktop and Android. That avoids adding a decoder to the bundle for a feature
 * most sessions never open - and a QR decoder is not a small dependency.
 *
 * Where it is unsupported (Safari, Firefox) the hook reports `supported: false`
 * rather than failing, and the screen offers manual entry instead. Degrading to
 * a text field is better than shipping 40kB of decoder to every user so that a
 * minority can point a camera.
 *
 * States: idle -> starting -> scanning -> (detected | error)
 */

const SCAN_INTERVAL_MS = 220;

export function useQrScanner({ onDetect } = {}) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const detectorRef = useRef(null);
  const settledRef = useRef(false);

  const [state, setState] = useState('idle');
  const [error, setError] = useState(null);
  const [torchOn, setTorchOn] = useState(false);
  const [torchAvailable, setTorchAvailable] = useState(false);

  const supported =
    typeof window !== 'undefined' && 'BarcodeDetector' in window;

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const start = useCallback(async () => {
    if (!supported) {
      setState('error');
      setError({
        code: 'UNSUPPORTED',
        message:
          'This browser cannot scan QR codes. Chrome or Edge can, or you can '
          + 'enter the UPI ID by hand.',
      });
      return;
    }

    settledRef.current = false;
    setState('starting');
    setError(null);

    try {
      // The rear camera, where there is a choice. `exact` would fail outright
      // on a laptop with only a front camera, so this is a preference.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });

      streamRef.current = stream;

      const [track] = stream.getVideoTracks();
      const capabilities = track?.getCapabilities?.() || {};
      setTorchAvailable(Boolean(capabilities.torch));

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      detectorRef.current = new window.BarcodeDetector({
        formats: ['qr_code'],
      });

      setState('scanning');

      // Polled rather than run per animation frame: a QR does not move, and
      // decoding every frame heats the phone for no extra hit rate.
      timerRef.current = setInterval(async () => {
        const video = videoRef.current;
        if (!video || video.readyState !== 4 || settledRef.current) return;

        try {
          const codes = await detectorRef.current.detect(video);
          const value = codes?.[0]?.rawValue;
          if (!value) return;

          // One scan per open. Without this the interval fires again while the
          // confirmation screen is loading and the same code is paid twice.
          settledRef.current = true;
          setState('detected');
          stop();
          onDetect?.(value);
        } catch {
          /* A frame that will not decode is the normal case, not an error. */
        }
      }, SCAN_INTERVAL_MS);
    } catch (err) {
      stop();
      setState('error');
      setError(describeCameraError(err));
    }
  }, [supported, onDetect, stop]);

  const toggleTorch = useCallback(async () => {
    const track = streamRef.current?.getVideoTracks?.()[0];
    if (!track) return;
    try {
      const next = !torchOn;
      await track.applyConstraints({ advanced: [{ torch: next }] });
      setTorchOn(next);
    } catch {
      setTorchAvailable(false);
    }
  }, [torchOn]);

  useEffect(() => stop, [stop]);

  return {
    videoRef,
    state,
    error,
    supported,
    torchOn,
    torchAvailable,
    start,
    stop,
    toggleTorch,
  };
}

/**
 * Camera failures, in words a user can act on.
 *
 * The browser's own messages name DOM exceptions; none of them tell someone
 * their camera is switched off or that another app has it.
 */
function describeCameraError(err) {
  const name = err?.name || '';

  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return {
      code: 'PERMISSION_DENIED',
      message:
        'Camera access was blocked. Allow it in your browser settings, then '
        + 'try again.',
    };
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return {
      code: 'NO_CAMERA',
      message: 'No camera was found on this device.',
    };
  }
  if (name === 'NotReadableError') {
    return {
      code: 'CAMERA_BUSY',
      message:
        'The camera is being used by another app. Close it and try again.',
    };
  }
  return {
    code: 'CAMERA_ERROR',
    message: 'The camera could not be started. Try again.',
  };
}

export default useQrScanner;

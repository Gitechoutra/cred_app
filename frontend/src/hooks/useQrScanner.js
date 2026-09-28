import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Camera QR scanning.
 *
 * Uses the browser's native BarcodeDetector where there is one - Chrome on
 * Android, macOS and ChromeOS - because it is fast and costs nothing to load.
 *
 * It is *not* on Chrome or Edge for Windows, nor on Safari or Firefox, which is
 * most laptops. This hook used to report those as unsupported and tell the user
 * to switch to Chrome - while they were in Chrome. Now it falls back to jsQR, a
 * small pure-JavaScript decoder, fetched on demand the first time it is needed:
 * sessions that never scan, or that have the native detector, never download
 * it. `supported` now only means "this browser can use a camera at all".
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
  // Which start() is current. Each start takes a number; stop() and any later
  // start() make older attempts stale, and a stale attempt cleans up after
  // itself instead of touching the live one.
  const runRef = useRef(0);

  const [state, setState] = useState('idle');
  const [error, setError] = useState(null);
  const [torchOn, setTorchOn] = useState(false);
  const [torchAvailable, setTorchAvailable] = useState(false);

  const supported =
    typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia);

  const stop = useCallback(() => {
    runRef.current += 1;
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
          'This browser cannot use a camera. Enter the UPI ID by hand instead.',
      });
      return;
    }

    stop();
    const run = runRef.current;
    const stale = () => run !== runRef.current;

    settledRef.current = false;
    setState('starting');
    setError(null);

    let stream = null;
    try {
      // The rear camera, where there is a choice. `exact` would fail outright
      // on a laptop with only a front camera, so this is a preference.
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });
      if (stale()) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = stream;

      const [track] = stream.getVideoTracks();
      const capabilities = track?.getCapabilities?.() || {};
      setTorchAvailable(Boolean(capabilities.torch));

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      const detect = await createDetector();
      if (stale()) return;
      detectorRef.current = detect;

      setState('scanning');

      // Polled rather than run per animation frame: a QR does not move, and
      // decoding every frame heats the phone for no extra hit rate.
      timerRef.current = setInterval(async () => {
        const video = videoRef.current;
        if (!video || video.readyState !== 4 || settledRef.current) return;

        try {
          const value = await detectorRef.current(video);
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
      // A superseded attempt fails as a matter of course - its play() is
      // interrupted by the newer one - and must not report an error or, worse,
      // stop the camera the newer attempt is now using. That is exactly what
      // happened under StrictMode's mount-unmount-mount: the first start's
      // AbortError tore down the second start's stream.
      if (stale()) {
        stream?.getTracks().forEach((track) => track.stop());
        return;
      }
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
 * A function that reads a QR code from the current video frame, or null.
 *
 * The native detector when the browser has one that handles QR, otherwise jsQR
 * on a downscaled frame - 640px on the long side is plenty for a QR held in
 * front of a camera, and keeps each attempt to a few milliseconds.
 */
async function createDetector() {
  if (typeof window !== 'undefined' && 'BarcodeDetector' in window) {
    try {
      const formats = await window.BarcodeDetector.getSupportedFormats?.();
      if (!formats || formats.includes('qr_code')) {
        const native = new window.BarcodeDetector({ formats: ['qr_code'] });
        return async (video) => (await native.detect(video))?.[0]?.rawValue || null;
      }
    } catch {
      /* Present but unusable - fall through to jsQR. */
    }
  }

  const { default: jsQR } = await import('jsqr');
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d', { willReadFrequently: true });

  return async (video) => {
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) return null;

    const scale = Math.min(1, 640 / Math.max(width, height));
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    return jsQR(frame.data, frame.width, frame.height, {
      inversionAttempts: 'dontInvert',
    })?.data || null;
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

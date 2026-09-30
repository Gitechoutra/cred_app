/**
 * Free the dev-server port before Vite starts.
 *
 * Runs automatically as npm's `predev` hook.
 *
 * Why this exists: vite.config.js sets `strictPort: true`, so Vite refuses to
 * drift to 3001 when 3000 is taken. That strictness is deliberate - the backend
 * has http://localhost:3000 baked into FRONTEND_BASE_URL and
 * CASHFREE_RETURN_URL, so a silently reassigned port would send users returning
 * from a 3DS challenge to a dead address. But it does mean an orphaned dev
 * server from a previous run blocks the next one, which is a tedious way to
 * start a day.
 *
 * The safety rule: only a Node process is killed. If something else holds the
 * port - a database, a corporate agent, another app - this reports it and steps
 * aside rather than terminating a process it does not understand.
 */

import { execSync } from 'node:child_process';

const PORT = Number(process.argv[2]) || 3000;
const isWindows = process.platform === 'win32';

function run(command) {
  try {
    return execSync(command, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch {
    // A non-zero exit here just means "nothing matched", which is the common
    // and entirely fine case.
    return '';
  }
}

/** PIDs listening on the port. */
function listeners() {
  if (isWindows) {
    const output = run(`netstat -ano -p TCP | findstr LISTENING | findstr :${PORT}`);

    return [
      ...new Set(
        output
          .split('\n')
          .map((line) => line.trim().split(/\s+/))
          // Match the local address column exactly, so port 30000 or a remote
          // address containing ":3000" is not mistaken for our listener.
          .filter((parts) => parts.length >= 5 && parts[1]?.endsWith(`:${PORT}`))
          .map((parts) => parts[parts.length - 1])
          .filter((pid) => pid && pid !== '0'),
      ),
    ];
  }

  return [
    ...new Set(
      run(`lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t`)
        .split('\n')
        .map((pid) => pid.trim())
        .filter(Boolean),
    ),
  ];
}

/** The executable name for a PID, lowercased. */
function processName(pid) {
  if (isWindows) {
    const output = run(`tasklist /FI "PID eq ${pid}" /NH /FO CSV`);
    const match = output.match(/^"([^"]+)"/m);
    return match ? match[1].toLowerCase() : '';
  }

  return run(`ps -p ${pid} -o comm=`).trim().toLowerCase();
}

function kill(pid) {
  run(isWindows ? `taskkill /PID ${pid} /F` : `kill -9 ${pid}`);
}

const pids = listeners();

if (pids.length === 0) {
  process.exit(0);
}

let freed = 0;

for (const pid of pids) {
  const name = processName(pid);

  if (name.toLowerCase().includes('docker')) {
    // Most likely CashU's own frontend container from an older
    // docker-compose.yml, which published it on 3000 (it is on 8080 now) and
    // restarts with Docker. That one is safe to stop - `docker compose up -d`
    // brings it back on its new port. Any other container is left alone.
    const containers = run(`docker ps --filter publish=${PORT} --format "{{.Names}}"`)
      .split('\n')
      .map((c) => c.trim())
      .filter(Boolean);
    const ours = containers.filter((c) => c.startsWith('cashu-'));

    if (ours.length && ours.length === containers.length) {
      for (const container of ours) run(`docker stop ${container}`);
      freed += 1;
      console.log(
        `  Freed port ${PORT} — stopped the old Docker container ${ours.join(', ')}.\n` +
          '  (The Docker stack now runs on 8080; `docker compose up -d` recreates it there.)',
      );
      continue;
    }

    console.warn(
      `\n  Port ${PORT} is held by Docker (PID ${pid})` +
        (containers.length ? `, container ${containers.join(', ')}.\n` : '.\n') +
        '  Leaving it alone — stop that container, or change the port in vite.config.js.\n',
    );
    continue;
  }

  if (!name.includes('node')) {
    console.warn(
      `\n  Port ${PORT} is held by "${name || 'an unknown process'}" (PID ${pid}), ` +
        'which is not a Node process.\n' +
        '  Leaving it alone — stop it yourself, or change the port in vite.config.js.\n',
    );
    continue;
  }

  kill(pid);
  freed += 1;
  console.log(`  Freed port ${PORT} — stopped an orphaned dev server (PID ${pid}).`);
}

// Wait for the socket to actually be released rather than guessing at it.
//
// This used to spin for a flat 400ms, which is a guess - and on Windows a
// killed process can hold the listener for longer than that, so Vite would
// still fail to bind and the whole hook would look like it had not run. Now it
// polls until the port is genuinely free, or gives up loudly after five
// seconds rather than letting Vite fail with a less useful message.
if (freed > 0) {
  const deadline = Date.now() + 5000;
  let released = false;

  while (Date.now() < deadline) {
    if (listeners().length === 0) {
      released = true;
      break;
    }
    sleep(120);
  }

  if (!released) {
    console.warn(
      `\n  Port ${PORT} is still held after stopping the process.\n` +
        '  Wait a moment and try again.\n',
    );
  }
}

/**
 * Sleep without an event loop.
 *
 * This script runs synchronously through execSync, so there is no loop to await
 * a timer on. Atomics.wait blocks the thread properly instead of burning a core
 * in a date-comparison spin.
 */
function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

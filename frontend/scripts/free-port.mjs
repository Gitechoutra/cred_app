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

// Give the OS a moment to release the socket, or Vite can still see it bound.
if (freed > 0) {
  const until = Date.now() + 400;
  while (Date.now() < until) {
    /* brief spin; execSync-based script has no event loop to await on */
  }
}

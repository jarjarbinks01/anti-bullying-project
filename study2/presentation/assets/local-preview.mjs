// Local-only launcher. Does not build, export, publish, or modify the candidate.
import { readFile, stat, lstat, open, unlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, dirname, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
const args = process.argv.slice(2);
const at = args.indexOf('--config');
if (at < 0 || !args[at + 1] || args.some((arg, i) =>
    i !== at && i !== at + 1 && arg !== '--check')) {
  throw new Error('Usage: local-preview.mjs --config /absolute/preview-config.json [--check]');
}
const configPath = resolve(args[at + 1]);
const sha256 = b => createHash('sha256').update(b).digest('hex');
const cfg = JSON.parse(await readFile(configPath, 'utf8'));
const site = resolve(cfg.site), secretPath = resolve(cfg.secret_file);
const manifestBytes = await readFile(resolve(site, 'snapshot-manifest.json'));
if (sha256(manifestBytes) !== cfg.manifest_sha256) throw new Error('Frozen manifest differs. Stop and review the candidate; do not regenerate it.');
const manifest = JSON.parse(manifestBytes);
let verified = 0;
for (const [name, digest] of Object.entries(manifest.files)) {
  const path = resolve(site, name);
  if (!path.startsWith(site + sep)) throw new Error('Unsafe manifest path.');
  if (sha256(await readFile(path)) !== digest) throw new Error('Frozen asset differs: ' + name);
  verified++;
}
const secStat = await lstat(secretPath), dirStat = await stat(dirname(secretPath));
if (!secStat.isFile() || secStat.isSymbolicLink() || (secStat.mode & 0o777) !== 0o600 ||
    (dirStat.mode & 0o777) !== 0o700 || secStat.uid !== process.getuid()) {
  throw new Error('Local credential storage is not private. Do not start.');
}
const secrets = JSON.parse(await readFile(secretPath, 'utf8'));
if (typeof secrets.STUDY2_ACCESS_PASSWORD !== 'string' || secrets.STUDY2_ACCESS_PASSWORD.length < 12 ||
    secrets.STUDY2_ACCESS_PASSWORD.length > 256 || typeof secrets.STUDY2_SESSION_SECRET !== 'string' ||
    secrets.STUDY2_SESSION_SECRET.length < 32 || secrets.STUDY2_SESSION_SECRET.length > 1024) {
  throw new Error('Local preview credentials are incomplete. Do not bypass login.');
}
if (!Number.isInteger(cfg.port) || cfg.port < 1024 || cfg.port > 65535) throw new Error('Invalid preview port.');
if (process.argv.includes('--check')) {
  console.log(JSON.stringify({ assets_verified: verified, manifest_verified: true, credentials_configured: true, credentials_private: true, url: `http://127.0.0.1:${cfg.port}`, release_id: manifest.release_id }));
  process.exit(0);
}
const pidPath = resolve(dirname(secretPath), 'preview-process.json');
try {
  const old = JSON.parse(await readFile(pidPath, 'utf8'));
  let running = false;
  try { process.kill(old.pid, 0); running = true; } catch (e) { if (e.code !== 'ESRCH') throw e; }
  if (running) throw new Error('A recorded preview process is already running. Check it before starting another.');
  await unlink(pidPath);
} catch (e) { if (e.code !== 'ENOENT') throw e; }
const pidFile = await open(pidPath, 'wx', 0o600);
await pidFile.writeFile(JSON.stringify({pid: process.pid, launcher: import.meta.filename, site, port: cfg.port, started_at: new Date().toISOString()}));
await pidFile.close();
let stopping = false;
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  try { const record = JSON.parse(await readFile(pidPath, 'utf8')); if (record.pid === process.pid) await unlink(pidPath); } catch {}
  process.exit(code);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
process.on('uncaughtException', () => { console.error('Preview stopped unexpectedly. Check port availability and the local configuration.'); void stop(1); });
process.env.STUDY2_ACCESS_PASSWORD = secrets.STUDY2_ACCESS_PASSWORD;
process.env.STUDY2_SESSION_SECRET = secrets.STUDY2_SESSION_SECRET;
process.env.PORT = String(cfg.port);
delete process.env.VERCEL;
setTimeout(() => { console.log('Eight-hour local preview limit reached.'); void stop(); }, Math.min(Number(cfg.max_session_hours) || 8, 8) * 3600000);
console.log(`Verified ${verified} frozen assets. Login is required. No publication or data update.`);
try { await import(pathToFileURL(resolve(site, 'preview.mjs')).href); }
catch { console.error('Could not start the frozen preview server.'); await stop(1); }

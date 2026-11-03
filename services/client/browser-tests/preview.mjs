import { preview } from 'vite';

const port = Number(process.argv[2]);
if (!Number.isSafeInteger(port) || port < 1 || port > 65535 || port === 7654) {
  throw new Error('Pass an owned, nondefault browser preview port');
}
const server = await preview({ preview: { host: '127.0.0.1', port, strictPort: true, proxy: {} } });
if (Object.keys(server.config.preview.proxy ?? {}).length) {
  throw new Error('Browser preview must not proxy API requests');
}
const stop = () => server.httpServer.close(() => process.exit(0));
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, stop);

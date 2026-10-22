import { mkdir, copyFile } from 'node:fs/promises';
import { build, context } from 'esbuild';
await mkdir('dist', { recursive: true });
for (const file of ['index.html', 'app.css']) await copyFile('src/' + file, 'dist/' + file);
const options = { entryPoints: ['src/app.mjs'], bundle: true, outfile: 'dist/app.js', format: 'esm', target: 'safari15', sourcemap: false };
await build({ entryPoints: ['src/account-theme.mjs'], bundle: true, outfile: 'dist/account-theme.js', format: 'iife', target: 'chrome80', loader: { '.css': 'text' }, sourcemap: false });
if (process.argv.includes('--serve')) {
  const ctx = await context(options);
  await ctx.watch();
  await ctx.serve({ servedir: 'dist', host: '127.0.0.1', port: 4173 });
  console.log('Local preview: http://127.0.0.1:4173 (no backend requests)');
} else { await build(options); }

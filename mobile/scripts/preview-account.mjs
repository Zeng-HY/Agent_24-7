// Local design fixture. No network calls, accounts or device commands.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
const fixture = await readFile(new URL('../tests/fixtures/account.html', import.meta.url), 'utf8');
const previewScript = `<script>
for(const id of ['login','register','reset','logout','bind','change'])document.getElementById(id).onclick=async()=>{
 const signed=document.getElementById('signed'), message=document.getElementById('message');
 if(id==='login'){signed.hidden=false;const list=document.getElementById('devices');list.replaceChildren();const li=document.createElement('li');li.append(document.createTextNode('设计预览电脑'));for(const text of ['连接','撤销']){const b=document.createElement('button');b.textContent=text;b.onclick=()=>{message.textContent='仅为界面预览，未连接任何电脑。'};li.append(b)}list.append(li)}
 else if(id==='logout')signed.hidden=true;
 else message.textContent='仅为界面预览，没有提交任何信息。';
};
</script><script src="/account-theme.js"></script>`;
createServer(async (request, response) => {
  const path = new URL(request.url, 'http://127.0.0.1').pathname;
  const files = { '/': ['index.html','text/html'], '/app.css': ['app.css','text/css'], '/app.js': ['app.js','text/javascript'], '/account-theme.js': ['account-theme.js','text/javascript'] };
  response.setHeader('Cache-Control', 'no-store');
  if (path === '/account') { response.setHeader('Content-Type','text/html; charset=utf-8'); response.end(fixture.replace('</body>', previewScript+'</body>')); return; }
  if (!files[path]) { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', files[path][1]+'; charset=utf-8');
  response.end(await readFile(new URL('../dist/'+files[path][0], import.meta.url)));
}).listen(4184, '127.0.0.1', () => console.log('Local-only design preview: http://127.0.0.1:4184/account'));

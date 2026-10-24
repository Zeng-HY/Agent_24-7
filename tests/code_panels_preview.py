"""Isolated phone preview for code/output panels; synthetic records only."""
import candidate_preview as preview

preview.SCENARIOS={'panels':'命令与结果｜灰色失败提示','markdown':'代码、Markdown 与提示词'}
COMMAND='Get-Content "D:/示例项目/中文 (1).txt"\n'+'\n'.join(f'Write-Output "第 {i+1} 行 '+('long-value '*14)+'"' for i in range(28))
RESULT='Exception: 这是脱敏测试结果，不代表正在执行真实命令。\n\n'+'\n'.join(f'结果第 {i+1} 行：检查输出边界与滚动位置。 '+('示例内容 '*10) for i in range(45))
MARKDOWN='# Markdown 源文本\n\n'+'\n'.join(f'- 第 {i+1} 项：这是可复制的原始 Markdown 文本。' for i in range(30))

def chat(cid,before=''):
    scene=cid.removeprefix('candidate-');rows=[preview.message('request','user','检查代码框分界、滚动和灰色失败状态。',0)]
    if scene=='panels':
        rows += [preview.message('progress','assistant','展开下面的工具项，分别滑动“命令”和“结果”。失败仅用灰字表示，普通过程文字不套框。',1,phase='commentary',activity_turn='panels'),
                 preview.message('failed','tool','执行测试脚本',2,activity_turn='panels',tool_status='failed',detail=COMMAND,result=RESULT),
                 preview.message('empty','tool','检查工作区',3,activity_turn='panels',tool_status='completed',detail='git status --short')]
    else:
        rows += [preview.message('reply','assistant','普通正文与 `行内代码` 保持原样。\n\n```markdown\n'+MARKDOWN+'\n```\n\n下面是短提示词，内容较少时不留大块空白。\n\n```text\n请根据给定材料提炼重点，保留事实与不确定性。\n```',1)]
    return dict(app='codex',id=cid,title=preview.SCENARIOS.get(scene,'代码面板候选'),status='running' if scene=='panels' else 'idle',messages=rows,has_more=False,next_cursor=None,activity_current='panels' if scene=='panels' else None,activity_turns={'panels':dict(started_at=preview.NOW,status='running',pauses=[])})

preview.chat=chat
preview.SEED=[]
preview.BOOT=r'''<script>
addEventListener('load',()=>{
 const row=el('div');row.style.cssText='display:flex;flex-wrap:wrap;gap:8px;padding:4px 12px;flex:none';
 const badge=el('span','','代码面板候选 · 仅脱敏样例');badge.style.cssText='font-size:12px;color:var(--muted);width:100%';row.append(badge);
 const theme=el('button','tp-button','切换深浅色'),update=el('button','tp-button','追加内容（保留滚动）');row.append(theme,update);document.querySelector('.cv-top').after(row);
 theme.onclick=()=>document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';
 update.onclick=()=>{if(!cur)return;clearTimeout(convTimer);readingUI.pauseStream();const rows=currentMessages.map(m=>({...m}));for(const m of rows){if(m.id==='failed')m.result+='\n新增结果：之前的框内滚动位置应保留。';if(m.id==='reply')m.text=m.text.replace('\n```','\n- 新增代码行：之前的框内滚动位置应保留。\n```');}renderMsgs(rows);};
});</script>'''

if __name__=='__main__':preview.main()

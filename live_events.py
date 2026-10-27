"""One authenticated SSE stream; only existing public message and control fields leave the host."""
import copy,json,time,select
from datetime import datetime,timezone
import chats
from codex_control import ordered_turns

def merge_live_messages(page,entry,state,previous=None):
    """Only uncommitted public items from the log's current turn may extend its tail.

    The last page is a reading window, not the set of all committed message IDs.
    In particular, a long turn's early commentary must never be appended again.
    """
    messages=list(page['messages']);ids={m['id'] for m in messages};live_ids=[]
    with entry.lock:
        def stored(item,turn_id):
            found=entry.by_id.get(item.get('id'))
            if found is not None:return found
            if item.get('type') not in (None,'agentMessage'):return None
            # Legacy logs use generated IDs. Limit exact-text fallback to this turn
            # and public legacy assistant messages; never compare reasoning items.
            text=chats.codex_answer(item.get('text') or '')  # as the log's copy reads (no memory notes, file links)
            candidates=[m for m in entry.messages if m.get('turn_id')==turn_id and m.get('legacy') and not m.get('source_id') and m['role']=='assistant' and (m.get('phase') or '')==(item.get('phase') or '') and m['text']==text]
            return candidates[0] if len(candidates)==1 else None
        def public(m):
            from activity_records import public_message
            result=public_message(m)
            result.pop('legacy',None)
            result.update(length=len(m['text']),truncated=len(m['text'])>6000,text=m['text'][:6000])
            return result
        # Promote live rows already shown by this connection even if their committed
        # version has since fallen outside the latest 60 rows.
        for old in (previous or {}).values():
            if not old.get('streaming'):continue
            m=stored(old,old.get('turn_id'))
            if m:
                if m['id'] not in ids:messages.append(public(m));ids.add(m['id'])
                if old['id']!=m['id']:
                    messages=[{**v,'projection_aliases':[old['id']]} if v['id']==m['id'] else v for v in messages]
            elif old.get('role')=='assistant' and old.get('phase') in (None,'','commentary','final_answer') and old['id'] not in ids:
                # Snapshot absence is not a retraction. Keep already public text
                # until its source record replaces it, including across turn ends.
                messages.append({**old,'sync_pending':True});ids.add(old['id'])
        turns=ordered_turns(state) if state and state.get('id')==page['id'] else []
        turn=turns[-1] if turns else None
        if (turn and turn.get('status')=='inProgress' and entry.state.get('running') is True
                and turn.get('turnId')==entry.state.get('current_turn_id')):
            items=turn.get('items',[])
            positions=getattr(entry,'_live_positions',{})
            entry._live_positions=positions
            anchor_cache={k:v for k,v in getattr(entry,'_live_anchor_ids',{}).items() if k[0]==turn['turnId']}
            entry._live_anchor_ids=anchor_cache
            positions={k:v for k,v in positions.items() if k[0]==turn['turnId']}
            entry._live_positions=positions
            for index,item in enumerate(items):
                if item.get('type')!='agentMessage' or item.get('phase') not in (None,'commentary','final_answer') or not item.get('text') or not item.get('id'):continue
                if stored(item,turn['turnId']) is not None:continue
                ident=item['id'];live_ids.append(ident)
                if ident in ids:
                    messages=[m for m in messages if m['id']!=ident];ids.discard(ident)
                # Position comes from adjacent source items. A snapshot's arrival
                # must not move every live message to the new log-file tail.
                anchors=[(i,stored(v,turn['turnId'])) for i,v in enumerate(items) if v.get('id')]
                before=next(((i,m) for i,m in reversed(anchors) if i<index and m),None)
                after=next(((i,m) for i,m in anchors if i>index and m),None)
                old=(previous or {}).get(ident,{})
                key=(turn['turnId'],ident)
                if before and after:
                    order=before[1]['order']+(after[1]['order']-before[1]['order'])*(index-before[0])/(after[0]-before[0])
                elif after:order=after[1]['order']-(after[0]-index)/(len(items)+1)
                else:
                    base=before[1]['order'] if before else entry.offset
                    anchor_id=before[1]['id'] if before else None
                    order=base+(index+1)/(len(items)+1) if before and anchor_cache.get(key)!=anchor_id else positions.get(key,old.get('order',base+(index+1)/(len(items)+1)))
                    anchor_cache[key]=anchor_id
                positions[key]=order
                text=chats.codex_answer(item['text']);messages.append({'id':ident,'source_id':ident,'role':'assistant','phase':item.get('phase') or '',
                    'turn_id':turn['turnId'],'order':order,
                    'source_sequence':index,'after_id':before[1]['id'] if before else None,'before_id':after[1]['id'] if after else None,
                    'time':datetime.fromtimestamp((turn.get('turnStartedAtMs') or 0)/1000,timezone.utc).isoformat(),
                    'text':text[:6000],'length':len(text),'truncated':len(text)>6000,'streaming':True})
                ids.add(ident)
    return messages,live_ids

def stream(handler,history,bridge,tasks,app,tid):
    if app=='deepseek':return deepseek_stream(handler,tid)
    watcher=None
    # Validate before switching the HTTP response into streaming mode.
    if app=='deepseek':history.conversation(app,tid,5)
    else:history.transcript(app,tid)
    if app=='codex':
        try:watcher=bridge.watch(tid)
        except Exception:watcher=None
    handler.send_response(200);handler.send_header('Content-Type','text/event-stream; charset=utf-8');handler.send_header('Cache-Control','no-cache, no-store');handler.send_header('X-Accel-Buffering','no');handler.end_headers()
    handler.connection.settimeout(15)
    seq=0;previous={};previous_control=None;previous_meta=None;previous_live_ids=None;last_write=0
    try:
        while True:
            if select.select([handler.connection],[],[],0)[0]:
                if not handler.connection.recv(1,2):break
            if app=='codex' and (watcher is None or watcher.closed):
                try:watcher=bridge.watch(tid)
                except Exception:watcher=None
            page=history.conversation(app,tid,60)
            control=bridge.status(tid) if app=='codex' else None
            if control is not None and tasks is not None:tasks.observe(tid,control)
            messages=page['messages'];live_ids=[];state=None
            if watcher is not None:
                with watcher.condition:record=watcher.snapshots.get(tid);state=copy.deepcopy(record[2]) if record else None
            if app=='codex':
                _,entry=history.transcript(app,tid)
                messages,live_ids=merge_live_messages(page,entry,state,previous)
                page={**page,'messages':messages}
            meta={k:page.get(k) for k in ('status','runtime','title','folder','activity_turns','activity_current')}
            clean_control={k:v for k,v in (control or {}).items() if k!='observed_at'}
            changed=[m for m in messages if previous.get(m['id'])!=m]
            if seq==0:payload={'type':'snapshot','protocol':1,'app':app,'id':tid,'chat':page,'control':control}
            elif changed or previous_control!=clean_control or previous_meta!=meta or previous_live_ids!=live_ids:
                payload={'type':'update','protocol':1,'app':app,'id':tid,'messages':changed,'meta':meta}
                if previous_control!=clean_control:payload['control']=control
            else:payload=None
            if payload is not None:
                seq+=1;payload['seq']=seq;payload['streaming_ids']=live_ids
                handler.wfile.write(('id: '+str(seq)+'\nevent: update\ndata: '+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n\n').encode('utf-8'));handler.wfile.flush();last_write=time.monotonic()
                previous={m['id']:copy.deepcopy(m) for m in messages};previous_control=copy.deepcopy(clean_control);previous_meta=copy.deepcopy(meta);previous_live_ids=list(live_ids)
            elif time.monotonic()-last_write>8:
                handler.wfile.write(b': heartbeat\n\n');handler.wfile.flush();last_write=time.monotonic()
            time.sleep(1)
    except Exception:pass
    finally:
        if watcher is not None:watcher.unwatch(tid)
        handler.close_connection=True


def deepseek_stream(handler,tid):
    """Forward the native follow stream, at most five display updates a second.

    A gap closes this SSE connection. The phone reconnects for a complete native
    baseline, including the active thinking/text prefix, without resending input.
    """
    import websocket
    import deepseek_control
    from deepseek_stream import Presentation,StreamGap
    from chat_history import HistoryError
    bridge=deepseek_control.bridge();socket=None
    try:
        item=bridge.find(tid);port,cookie=bridge.client.connection_info()
        socket=websocket.create_connection(f'ws://127.0.0.1:{port}/api/remote.mux',cookie=cookie,
            origin=f'http://127.0.0.1:{port}',timeout=8,http_no_proxy=['127.0.0.1'])
        socket.send(json.dumps({'type':'open','streamId':'history','endpoint':'session/follow',
            'payload':{'args':{'request':{'address':{'kind':'session','sessionId':tid},'assistantStream':True,'maxMessages':60}}}}))
        first=json.loads(socket.recv())
        if first.get('type')!='item' or first.get('streamId')!='history' or first.get('value',{}).get('type')!='snapshot':
            raise StreamGap('Missing follow snapshot')
        presentation=Presentation(tid,item);presentation.accept(first['value'])
        projections=first['value'].get('projections') or {};values=projections.get('values',projections)
        try:presentation.set_subagent_status(bridge._subagents(tid,values))
        except Exception:pass
    except Exception:
        if socket:socket.close()
        raise HistoryError('DeepSeek 实时连接暂不可用，请稍后重试',503) from None
    handler.send_response(200);handler.send_header('Content-Type','text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control','no-cache, no-store');handler.send_header('X-Accel-Buffering','no');handler.end_headers()
    handler.connection.settimeout(15);socket.settimeout(.2)
    sequence=0;previous={};previous_meta=None;previous_live=None;last_write=0;last_update=0;dirty=True;last_subs=0
    try:
        while True:
            if select.select([handler.connection],[],[],0)[0] and not handler.connection.recv(1,2):break
            now=time.monotonic()
            if dirty and (sequence==0 or now-last_update>=.2):
                page,live=presentation.page();messages=page['messages']
                meta={k:page.get(k) for k in ('status','runtime','title','folder','activity_turns','activity_current')}
                changed=[m for m in messages if previous.get(m['id'])!=m]
                if sequence==0:payload={'type':'snapshot','protocol':1,'app':'deepseek','id':tid,'chat':page,'control':None}
                elif changed or meta!=previous_meta or live!=previous_live:
                    payload={'type':'update','protocol':1,'app':'deepseek','id':tid,'messages':changed,'meta':meta}
                else:payload=None
                if payload is not None:
                    sequence+=1;payload.update(seq=sequence,streaming_ids=live)
                    handler.wfile.write(('id: '+str(sequence)+'\nevent: update\ndata: '+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n\n').encode('utf-8'));handler.wfile.flush()
                    previous={m['id']:m for m in messages};previous_meta=meta;previous_live=live;last_write=now
                dirty=False;last_update=now
            if now-last_write>8:
                handler.wfile.write(b': heartbeat\n\n');handler.wfile.flush();last_write=now
            if now-last_subs>=5:
                # a subagent may finish while this conversation stays open: refresh its card's status
                last_subs=now
                try:
                    if presentation.set_subagent_status(bridge._subagents(tid,values)):dirty=True
                except Exception:pass
            try:raw=socket.recv()
            except websocket.WebSocketTimeoutException:continue
            if not raw:break
            frame=json.loads(raw)
            if frame.get('streamId')!='history':continue
            if frame.get('type')!='item':break
            presentation.accept(frame['value']);dirty=True
    except (OSError,ValueError,KeyError,TypeError,websocket.WebSocketException):pass
    finally:
        socket.close();handler.close_connection=True

/* Navigation and motion for the phone page: one back action (button, edge drag, Safari history), the chat
   sliding in over the list and back out, the drawer as a ChatGPT-style card pushed aside, bottom sheets that
   slide up and can be dragged down, and a light haptic tick at the key moments. */
(() => {
  const view=$('convView'),shield=el('div'),edge=el('div'),drawer=$('navSheet'),drawerBox=drawer.querySelector('.box'),deco=el('div','nav-edge');
  shield.id='chatBackdrop';edge.id='backGestureEdge';shield.setAttribute('aria-hidden','true');edge.setAttribute('aria-hidden','true');document.body.append(shield,edge);
  deco.setAttribute('aria-hidden','true');deco.append(el('i','nav-shadow'));drawer.append(deco);
  const EASE='cubic-bezier(.32,.72,0,1)',PUSH=.3,DIM=.1,FULL=360,R=40,SHEET='.sheet:not(.drawer):not(.popover):not(.dialog-sheet)';
  const style=el('style');style.textContent=`#chatBackdrop{display:none;position:fixed;inset:0;z-index:39;background:#fff;pointer-events:none}body.chat-open #chatBackdrop{display:block}body.chat-open>header,body.chat-open>[data-mode]{visibility:hidden}body.chat-open #convView{overscroll-behavior:none}#cvMsgs{overscroll-behavior-y:contain}
#backGestureEdge{position:fixed;left:0;top:var(--chat-top,0px);height:var(--chat-height,100dvh);width:20px;z-index:41;display:none;touch-action:pan-y}body.chat-open:not(.has-overlay) #backGestureEdge{display:block}body[data-current-mode="chat"]:not(.chat-open):not(.has-overlay) #backGestureEdge{display:block;top:0;height:100dvh}
body.chat-motion.chat-open>header,body.chat-motion.chat-open>[data-mode]{visibility:visible}body.chat-motion #chatBackdrop{display:block;background:#000;opacity:0}#convView.chat-moving{box-shadow:-8px 0 24px rgba(0,0,0,.08)}#convView.chat-leaving{pointer-events:none}
.sheet:not(.is-open){pointer-events:none}
#navSheet{background:transparent;opacity:1;transition:none}#navSheet .box{width:300px;background:var(--bg);border-radius:0;box-shadow:none;overflow:hidden;transform:translate3d(-100%,0,0);transition:none}
#navSheet .nav-edge{position:absolute;top:0;bottom:0;left:0;width:${R}px;z-index:1;pointer-events:none;opacity:0;background:radial-gradient(circle at 100% 100%,transparent ${R-1}px,var(--bg) ${R}px) top left/${R}px ${R}px no-repeat,radial-gradient(circle at 100% 0,transparent ${R-1}px,var(--bg) ${R}px) bottom left/${R}px ${R}px no-repeat}
#navSheet .nav-shadow{position:absolute;top:0;bottom:0;right:100%;width:28px;background:linear-gradient(to left,rgba(29,35,48,.13),rgba(29,35,48,0))}
#navSheet .nav-strip{position:absolute;top:0;left:300px;width:90px;height:100%;min-height:0;margin:0;padding:0;opacity:.01;z-index:2;-webkit-tap-highlight-color:transparent}
@media (max-width:699.98px){${SHEET}{opacity:1;background-color:rgba(29,35,48,0);transition:background-color .28s ease}${SHEET}.is-open{background-color:rgba(29,35,48,.22);transition-duration:.36s}${SHEET} .box{transform:translate3d(0,100%,0);transition:transform .28s ${EASE}}${SHEET}.is-open .box{transform:none;transition-duration:.42s}}`;
  document.head.append(style);

  // A light haptic tick where the phone allows one from a web page. Android: navigator.vibrate(10).
  // iPhone Safari has no navigator.vibrate; its switch control (<input type=checkbox switch>) ticks when it
  // toggles, and code once used that by clicking a hidden switch. Tested 10-11 on the user's iPhone (iOS 26):
  // only a finger on the switch itself ticks; a switch toggled by script never does (hidden or drawn, through
  // its label or directly, even the very switch that ticks under the finger). So on the iPhone this is a no-op,
  // and swipes (drawer, back drag) cannot tick there at all. Call it inside the touch or click handler.
  function haptic(){try{if(typeof navigator.vibrate==='function')navigator.vibrate(10);}catch(e){}}
  document.addEventListener('click',e=>{if(e.target.closest?.('#cvBtn,#newBtn'))haptic();},true); // a disabled send button fires no click
  // The one way left for taps on the iPhone (row 6 of the 10-11 test ticked): a see-through switch laid over the
  // button, so the finger really lands on a switch; its click then bubbles to the button, which does its job.
  // A disabled button lets taps through its switch. If the button's content is replaced (icons), the switch
  // comes back. Safari does not move focus to a tapped checkbox; focus is put back anyway, to keep the keyboard.
  const tcss=el('style');tcss.textContent='.tap-host{position:relative}.tap-tick{position:absolute;inset:0;width:100%;height:100%;min-height:0;margin:0;padding:0;opacity:.01;z-index:3;-webkit-tap-highlight-color:transparent}button:disabled>.tap-tick,.tick-off .tap-tick{pointer-events:none}';document.head.append(tcss);
  function tapTick(btn){
    if(!btn||btn._tapTick)return;const sw=document.createElement('input');sw.type='checkbox';sw.setAttribute('switch','');sw.className='tap-tick';sw.tabIndex=-1;sw.setAttribute('aria-hidden','true');btn._tapTick=sw;
    sw.addEventListener('pointerdown',()=>{sw._prev=document.activeElement;});
    sw.addEventListener('click',()=>{const a=sw._prev;sw._prev=null;if(a&&a!==document.body&&a!==document.activeElement&&a.isConnected)a.focus({preventScroll:true});});
    btn.append(sw);new MutationObserver(()=>{if(sw.parentNode!==btn)btn.append(sw);}).observe(btn,{childList:true});
    // Only a positioned button keeps its switch inside it. A button built before it is in the page cannot tell its
    // position yet (a switch of a not-yet-placed button once covered a whole sheet), so the switch stays hidden,
    // and the tap goes to the button itself, until the button is placed and checked.
    let tries=0;sw.style.visibility='hidden';
    const place=()=>{if(!btn.isConnected){if(++tries<30)requestAnimationFrame(place);return;}if(getComputedStyle(btn).position==='static')btn.classList.add('tap-host');sw.style.visibility='';};place();
  }
  // The visible strip of the pushed card closes the drawer: a switch over it, so that tap ticks too.
  const strip=document.createElement('input');strip.type='checkbox';strip.setAttribute('switch','');strip.className='nav-strip';strip.tabIndex=-1;strip.setAttribute('aria-label','收起侧边栏');
  strip.addEventListener('click',()=>{if(overlays.at(-1)?.id===drawer.id)closeSheet(drawer.id);});drawer.append(strip);
  // Never over something you scroll: a finger that lands on a switch belongs to the switch (WebKit's
  // CheckboxInputType::handleTouchEvent marks that touchstart handled), so with one on every row the conversation list
  // could not be scrolled and each swipe became a tap (the user's iPhone, 10-11). Rows tick another way (tapLabel below);
  // panels whose content scrolls set their switches aside (tickRoom).
  function attachTicks(){
    for(const sel of ['#cvBtn','#newBtn','header button[aria-label="打开导航"]','#navSheet .sh-head button','#settingsBtn','.mic-btn','.cv-top .back','.stop-turn','.composer-tools button','.composer-chip','#newAdd'])document.querySelectorAll(sel).forEach(tapTick);
    const list=$('convList');if(list){const rows=()=>list.querySelectorAll('.conv').forEach(tapLabel);rows();new MutationObserver(rows).observe(list,{childList:true});} // the list is rebuilt on every refresh
  }
  // A real tap on a <label> reaches its switch as a trusted click (WebKit: HTMLLabelElement::defaultEventHandler calls
  // dispatchSimulatedClick, trusted when the tap was), and a trusted click on a switch ticks. A script's click is not
  // trusted, which is why the 10-11 test's scripted switches never ticked. Here the finger lands on the label, an ordinary
  // element; the one switch all rows' labels point at is a 1 px dot outside <body>, which takes no touches and is never
  // made inert (opening the chat makes the list inert before the label passes its click on). The list still scrolls.
  const lcss=el('style');lcss.textContent='.tap-label{position:absolute;inset:0;z-index:2;-webkit-tap-highlight-color:transparent}#lbrTapSource{position:fixed;left:0;top:0;width:1px;height:1px;min-height:0;margin:0;padding:0;opacity:.01;pointer-events:none;z-index:-1}';document.head.append(lcss);
  const tapSource=document.createElement('input');tapSource.type='checkbox';tapSource.setAttribute('switch','');tapSource.id='lbrTapSource';tapSource.tabIndex=-1;tapSource.setAttribute('aria-hidden','true');document.documentElement.append(tapSource);
  function tapLabel(row){
    if(!row||row._tapLabel)return;const label=document.createElement('label');label.className='tap-label';label.htmlFor=tapSource.id;label.setAttribute('aria-hidden','true');
    row._tapLabel=label;row.classList.add('tap-host');row.append(label);
  }
  if(document.readyState==='complete')attachTicks();else window.addEventListener('load',attachTicks,{once:true}); // after every script has built its buttons

  let drag=null,swipe=null,shutStart=null,sheetDrag=null,busy=false,rootScroll=0,epoch=0,frame=0,lastTop=null,sheetPlanned=null;
  const nav={x:0,n:0,open:false,token:0,planned:null,gesture:false},chat={token:0,shown:false,leaving:false,exiting:false};
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  // No motion with Reduce Motion on, in the background, or before the first touch: on load restoreScene()
  // reopens the last chat, and that should just appear.
  const animOK=()=>!reduced()&&!document.hidden&&(navigator.userActivation?.hasBeenActive??true);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),N=()=>Math.round(Math.min(320,innerWidth*.74));
  const pageNodes=()=>document.querySelectorAll('body>header,body>section'); // recomputed: activity-ui adds its section later
  const isPhoneSheet=n=>!!n?.matches?.(SHEET)&&matchMedia('(max-width:699.98px)').matches;

  // Finger speed over the last ~90 ms (px/ms) and the release rule shared by every drag: past 30% of the way
  // (110 px at most) or a quick flick, never when flung back. The settle continues at the finger's speed
  // (2.25 is the starting slope of EASE), otherwise it takes 220-380 ms by distance left.
  function track(d,x,y){const now=performance.now();(d.s||(d.s=[])).push([now,x,y]);while(d.s.length>2&&now-d.s[0][0]>90)d.s.shift();}
  function speed(d,axis){const s=d.s||[];if(s.length<2)return 0;const a=s[0],b=s.at(-1),dt=b[0]-a[0];return dt>0?(b[axis]-a[axis])/dt:0;}
  function commits(travel,v,span){return v>=-.3&&(travel>Math.min(110,span*.3)||(travel>45&&v>.5));}
  function settleMs(rem,total,v){if(reduced())return 0;return Math.round(v>.2?clamp(2.25*rem/v,160,420):220+160*rem/Math.max(1,total));}
  function setT(n,ms,props){n.style.transition=ms?props.map(p=>`${p} ${ms}ms ${EASE}`).join(','):'none';}

  // ------------------------------------------------------------------ the drawer: a card pushed aside
  // The page itself moves right as the card; the drawer stays above it, its box ending where the card begins.
  // The box clips its contents, which move the other way so they look still and get revealed (as in ChatGPT).
  // The card's rounded corners and the shadow it casts are painted by .nav-edge in the drawer's colour.
  function navPaint(x,ms){
    nav.x=x;const n=nav.n||N();
    setT(drawerBox,ms,['transform']);drawerBox.style.transform=`translate3d(${x-n}px,0,0)`;
    for(const k of drawerBox.children){setT(k,ms,['transform','opacity']);k.style.transform=`translate3d(${n-x}px,0,0)`;k.style.opacity=String(n?x/n:0);}
    setT(deco,ms,['transform','opacity']);deco.style.transform=`translate3d(${x}px,0,0)`;deco.style.opacity=String(Math.min(1,x/24));
    for(const p of pageNodes()){setT(p,ms,['transform']);p.style.transform=x?`translate3d(${x}px,0,0)`:'';}
  }
  // While the drawer shows, the page moved right must not widen the document, or the browser zooms the page
  // out mid-slide (innerWidth went 390 -> 679 in a test, even with body overflow hidden). So from the first frame
  // until the drawer is hidden again: the window is locked through <html> (hidden), and <body> clips sideways
  // (clip, not hidden, so it does not become a scroller and the sticky header still sticks to the window).
  // The drawer width is measured once per showing.
  function navLock(){document.documentElement.style.overflow='hidden';document.body.style.overflow='clip visible';}
  function navShow(){
    clearTimeout(drawer._closing);if(drawer.style.display!=='block'||!nav.n)nav.n=N();
    drawer.style.display='block';if(!drawer.style.zIndex)drawer.style.zIndex='60';drawerBox.style.width=nav.n+'px';navLock();
    strip.style.left=nav.n+'px';strip.style.width=Math.max(0,innerWidth-nav.n)+'px';
    if(!overlays.some(o=>o.id===drawer.id))drawer.inert=true;
  }
  function navNow(){if(drawer.style.display!=='block'||!drawerBox.style.transform)return nav.x;try{return clamp(new DOMMatrixReadOnly(getComputedStyle(drawerBox).transform).m41+nav.n,0,nav.n);}catch(e){return nav.x;}}
  function navTo(x,ms,done){const token=++nav.token;navPaint(navNow(),0);drawerBox.offsetWidth;navPaint(x,ms);if(!ms){done?.();return;}setTimeout(()=>{if(token===nav.token)done?.();},ms+50);}
  function navSettled(){ // closed for real: hide the drawer and give the page back its own position
    if(overlays.some(o=>o.id===drawer.id))return;
    nav.token++;nav.x=0;nav.n=0;drawer.style.display='none';drawer.inert=false;
    for(const n of [drawerBox,deco,...drawerBox.children]){n.style.transform='';n.style.transition='';n.style.opacity='';}drawerBox.style.width='';
    for(const p of pageNodes()){p.style.transform='';p.style.transition='';}
    document.documentElement.style.overflow='';document.body.style.overflow=overlays.length||cur?'hidden':''; // as syncInert would have it
    if(scrollX)window.scrollTo(0,scrollY);
  }
  function finishNav(){nav.token++;if(overlays.some(o=>o.id===drawer.id)){navShow();navPaint(nav.n,0);}else if(drawer.style.display==='block'||nav.x)navSettled();}
  // Every way of opening or closing it (menu button, X, the visible strip, a mode switch, a drag, Safari back)
  // passes through openSheet/hideOverlay -> syncInert -> sync(), still inside the user's tap: tick there.
  function navToggled(open){
    const ms=nav.planned??(animOK()?FULL:0),now=nav.gesture;nav.planned=null;nav.gesture=false;haptic();
    if(open){
      navShow();navTo(nav.n,ms);
      // opened with a tap: its contents arrive one after another (sidebar-ui.js), done when the drawer stops (10-14: they
      // used to run on 0.18 s after it, and the end looked unsteady). Not after a drag: they were on show under the finger
      // all along, and would blink.
      if(!now&&ms){clearTimeout(nav.entering);drawerBox.classList.add('lbr-entering');nav.entering=setTimeout(()=>drawerBox.classList.remove('lbr-entering'),ms+120);}
      return;
    }
    navLock(); // hideOverlay -> syncInert just unlocked the page; keep it locked until the drawer is hidden
    if(now||!ms){navShow();navTo(0,ms,navSettled);return;}
    // a tap closed it: start a frame later, so sections a mode switch has just shown move from the card's place too
    const token=++nav.token;requestAnimationFrame(()=>{if(token!==nav.token)return;navShow();navTo(0,ms,navSettled);});
  }
  function navBegin(t){finishChat();clearTimeout(drawer._shut);navShow();const x=navNow();nav.token++;navPaint(x,0);const d={kind:'nav',x:t.clientX,y:t.clientY,base:x,now:x,open:overlays.some(o=>o.id===drawer.id)};track(d,t.clientX,t.clientY);return d;}
  function navMove(d,t){track(d,t.clientX,t.clientY);d.now=clamp(d.base+t.clientX-d.x,0,nav.n);cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(drag===d)navPaint(d.now,0);});}
  function navEnd(d,allow){
    cancelAnimationFrame(frame);const n=nav.n,x=d.now,v=speed(d,1);navPaint(x,0);
    if(d.open){const close=allow&&commits(n-x,-v,n);if(close){nav.planned=settleMs(x,n,-v);nav.gesture=true;closeSheet(drawer.id);}else navTo(n,settleMs(n-x,n,v));}
    else{const open=allow&&commits(x,v,n);if(open){nav.planned=settleMs(n-x,n,v);nav.gesture=true;openSheet('navSheet');}else navTo(0,settleMs(x,n,-v),navSettled);}
  }

  // ------------------------------------------------------------------ the chat: pushed in over the list
  // p is how far the chat is in (1 = covering the screen). While it moves the list shows under it, shifted
  // left by up to 30% and dimmed by the backdrop; at rest everything is back to plain: list hidden, white backdrop.
  function chatPaint(p,ms){
    const w=innerWidth,x=-PUSH*w*p;
    setT(view,ms,['transform']);view.style.transform=p>=1?'':`translate3d(${Math.round((1-p)*w)}px,0,0)`;
    setT(shield,ms,['opacity']);shield.style.opacity=String(DIM*p);
    for(const n of pageNodes()){setT(n,ms,['transform']);n.style.transform=x?`translate3d(${x}px,0,0)`:'';}
  }
  function chatStart(){document.body.classList.add('chat-motion');view.classList.add('chat-moving');}
  function chatNow(){if(view.style.display==='none')return 0;if(!view.classList.contains('chat-moving'))return 1;try{return clamp(1-new DOMMatrixReadOnly(getComputedStyle(view).transform).m41/innerWidth,0,1);}catch(e){return 1;}}
  function chatTo(from,to,ms,done){const token=++chat.token;chatPaint(from,0);view.offsetWidth;chatPaint(to,ms);if(!ms){done?.();return;}setTimeout(()=>{if(token===chat.token)done?.();},ms+50);}
  function chatRest(){
    chat.token++;chat.exiting=false;view.classList.remove('chat-leaving');if(!document.body.classList.contains('chat-motion'))return;
    document.body.classList.remove('chat-motion');view.classList.remove('chat-moving');
    for(const n of [view,shield,...pageNodes()]){n.style.transform='';n.style.transition='';}shield.style.opacity='';
  }
  function finishChat(){if(!cur&&chat.exiting)view.style.display='none';chatRest();}
  function onOpen(){
    const fromList=!chat.shown||chat.exiting,from=chat.exiting?chatNow():0;
    chat.shown=true;chat.leaving=false;epoch++;busy=false;cancelGesture();
    // Picked in the drawer (sidebar-ui.js): the chat is already in place under the drawer, whose own closing (started by
    // openConv's dismissOverlays) slides it away over the chat. No slide-in from the right, and the drawer is not cut short.
    if(viaDrawer){rootScroll=scrollY;sync();syncInert();finishChat();return;}
    finishNav();rootScroll=scrollY;sync();syncInert();
    if(fromList&&animOK()){chat.exiting=false;view.classList.remove('chat-leaving');chatStart();chatTo(from,1,FULL,chatRest);}else finishChat();
  }
  let viaDrawer=false;
  function openFromDrawer(open){viaDrawer=true;try{open();}finally{viaDrawer=false;}}
  // Each time the keyboard opens in a chat, iPhone Safari pushes the hidden list down by about 500 px and
  // never undoes it (logs/viewport_trace.jsonl, 10-11: 529, 1031, 1560). Put the list back where it was
  // left before it shows: when a back drag starts, and right away on close (the next frame checks again).
  function listBack(){if(Math.abs(scrollY-rootScroll)>1)window.scrollTo(0,rootScroll);}
  function onClose(){
    const dragged=chat.leaving;chat.leaving=false;chat.shown=false;epoch++;busy=false;cancelGesture();sync();syncInert();
    if(!cur){listBack();requestAnimationFrame(()=>{if(!cur)listBack();});}
    if(dragged||cur||!animOK()){finishChat();return;}
    // closeConv hid the chat in this same task; show it again for the slide out (nothing is drawn in between)
    view.style.display='flex';const from=document.body.classList.contains('chat-motion')?chatNow():1;
    if(view.contains(document.activeElement))document.activeElement.blur();
    chat.exiting=true;view.classList.add('chat-leaving');chatStart();chatTo(from,0,FULL,()=>{if(!cur)view.style.display='none';chatRest();});
  }
  function parentExists(){return !!history.state?.remoteUI?.parent;}
  function back(){if(busy)return;if(overlays.length){closeSheet(overlays.at(-1).id);return;}if(!cur)return;workspaceUI?.saveScene();busy=true;
    if(parentExists()){history.back();const expected=epoch;setTimeout(()=>{if(busy&&epoch===expected){busy=false;closeConv(true);replaceUIState();}},700);}
    else{busy=false;closeConv(true);replaceUIState();}}
  // A finished back drag: the chat stays slid out until it is really closed. Putting it back first and then
  // going back drew it over the list once more, because Safari answers history.back() a frame or more later
  // (popstate). Closing (popstate, the 700 ms fallback, or no parent) runs onClose, which tidies up.
  function leave(){if(busy||!cur||overlays.length){chat.leaving=false;finishChat();return;}back();if(!busy&&cur){chat.leaving=false;finishChat();}}
  function pop(event){
    // Panels are ephemeral: browser Back closes the visible panel, never resurrects stale approval UI.
    if(overlays.length){hideOverlay(overlays[0].id);history.pushState({remoteUI:uiState()},'');busy=false;cancelGesture();return;}
    epoch++;busy=false;cancelGesture();applyHistoryState(event.state?.remoteUI||{mode:'chat',conv:null,overlays:[]});sync();
    if(cur&&chat.leaving){chat.leaving=false;finishChat();} // went back to another chat, or nowhere: show this one again
  }
  function chatBegin(t){finishChat();chat.token++;chatStart();chatPaint(1,0);const d={kind:'chat',x:t.clientX,y:t.clientY,dx:0};track(d,t.clientX,t.clientY);return d;}
  function chatMove(d,t,dx){
    if(!d.moved&&dx>0&&(dx>8||!typingField())){d.moved=true;if(typingField())document.activeElement.blur();listBack();}
    track(d,t.clientX,t.clientY);d.dx=clamp(dx,0,innerWidth);cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(drag===d)chatPaint(1-d.dx/innerWidth,0);});
  }
  function chatEnd(d,allow){
    cancelAnimationFrame(frame);const w=innerWidth,v=speed(d,1),p=1-d.dx/w;
    if(allow&&commits(d.dx,v,w)){haptic();chat.leaving=true;chatTo(p,0,settleMs(w-d.dx,w,v),leave);}
    else chatTo(p,1,settleMs(d.dx,w,-v),chatRest);
  }

  // ------------------------------------------------------------------ gestures
  function endDrag(allow){const d=drag;drag=null;if(!d)return;if(d.kind==='chat')chatEnd(d,allow);else navEnd(d,allow);}
  function cancelGesture(){
    cancelAnimationFrame(frame);const d=drag;drag=null;swipe=null;shutStart=null;
    if(d?.kind==='nav'&&!overlays.some(o=>o.id===drawer.id))navTo(0,0,navSettled);
    if(sheetDrag){const s=sheetDrag;sheetDrag=null;sheetClear(s.node);}
  }
  function reset(){cancelGesture();finishNav();finishChat();}
  // The 20 px left edge: drags the chat back, or pulls the drawer out on the list. Cancelling touchstart here
  // is what keeps Safari's own back swipe away (iOS 13.4+).
  edge.addEventListener('touchstart',e=>{if(e.touches.length!==1||(!cur&&mode!=='chat')||overlays.length||busy||drag||workspaceUI?.composing||!e.cancelable)return;
    e.preventDefault();const t=e.touches[0];drag=cur?chatBegin(t):navBegin(t);
  },{passive:false});
  edge.addEventListener('touchmove',e=>{if(!drag)return;if(e.touches.length!==1){endDrag(false);return;}const t=e.touches[0],dx=t.clientX-drag.x,dy=t.clientY-drag.y;
    if(Math.abs(dy)>24&&Math.abs(dy)>Math.abs(dx)){endDrag(false);return;}if(e.cancelable)e.preventDefault();
    if(drag.kind==='chat')chatMove(drag,t,dx);else navMove(drag,t);
  },{passive:false});
  edge.addEventListener('touchend',()=>endDrag(true));edge.addEventListener('touchcancel',()=>endDrag(false));
  // Anywhere on the list: a mostly rightward first move pulls the drawer out; anything else stays a scroll or a tap.
  const boundPage=new WeakSet();
  function bindPage(n){if(boundPage.has(n))return;boundPage.add(n);
    n.addEventListener('touchstart',e=>{swipe=null;if(e.touches.length!==1||cur||overlays.length||busy||drag||mode!=='chat'||workspaceUI?.composing)return;
      const t=e.touches[0],target=e.target;if(target.closest?.('input:not(.tap-tick),textarea,select,[contenteditable]'))return; // a row's tick switch still swipes
      for(let p=target;p&&p!==n.parentNode;p=p.parentElement)if(p.scrollLeft>0)return; // a strip scrolled sideways keeps its swipe
      swipe={x:t.clientX,y:t.clientY};},{passive:true});
    n.addEventListener('touchmove',e=>{
      if(drag?.page){if(e.touches.length!==1){endDrag(false);return;}if(e.cancelable)e.preventDefault();navMove(drag,e.touches[0]);return;}
      if(!swipe)return;const t=e.touches[0],dx=t.clientX-swipe.x,dy=t.clientY-swipe.y;if(Math.hypot(dx,dy)<6)return;
      const s=swipe;swipe=null;if(!(dx>0&&dx>1.2*Math.abs(dy)&&e.cancelable))return;
      e.preventDefault();drag=navBegin({clientX:s.x,clientY:s.y});drag.page=true;navMove(drag,t);
    },{passive:false});
    n.addEventListener('touchend',()=>{swipe=null;if(drag?.page)endDrag(true);});n.addEventListener('touchcancel',()=>{swipe=null;if(drag?.page)endDrag(false);});
  }
  // The open drawer goes back the way it came: drag it left, or flick, to close it; a short drag springs back.
  drawer.addEventListener('touchstart',e=>{shutStart=null;if(e.touches.length!==1||overlays.at(-1)?.id!==drawer.id||drag)return;const t=e.touches[0];shutStart={x:t.clientX,y:t.clientY};},{passive:true});
  drawer.addEventListener('touchmove',e=>{
    if(drag?.shut){if(e.touches.length!==1){endDrag(false);return;}if(e.cancelable)e.preventDefault();navMove(drag,e.touches[0]);return;}
    if(!shutStart)return;const t=e.touches[0],dx=t.clientX-shutStart.x,dy=t.clientY-shutStart.y;if(Math.abs(dx)<10&&Math.abs(dy)<10)return;
    const s=shutStart;shutStart=null;if(dx>=0||Math.abs(dy)>=Math.abs(dx)||!e.cancelable)return;
    e.preventDefault();drag=navBegin({clientX:s.x,clientY:s.y});drag.shut=true;navMove(drag,t);
  },{passive:false});
  drawer.addEventListener('touchend',()=>{shutStart=null;if(drag?.shut)endDrag(true);});drawer.addEventListener('touchcancel',()=>{shutStart=null;if(drag?.shut)endDrag(false);});

  // ------------------------------------------------------------------ bottom sheets (phones)
  // They slide up (CSS above, after openSheet commits the closed state) and can be dragged down to close:
  // from the title row, or from the content once it is scrolled to the top. Fields keep their own touches.
  const boundSheet=new WeakSet();
  function sheetClear(node){const box=node.querySelector('.box');if(box){box.style.transform='';box.style.transition='';}node.style.backgroundColor='';node.style.transition='';}
  // In every panel and menu (bottom sheets, popovers, dialogs), choices and menu items tick when tapped: models,
  // effort, modes, answers, 拍照/从相册选择, and the main button (应用, 提交, 确定). Their buttons are often built
  // after the panel opens, so new ones are picked up as they appear.
  // When the content is taller than the panel, its switches let taps through to the buttons (no tick there), so the
  // panel can still be scrolled.
  const boundTicks=new WeakSet(),TICKED='[role=radio],[role=checkbox],.effort-choices button,.menu-row,.option-card,.model-list-row,button.big';
  function tickRoom(node){const body=node.querySelector('.sh-body');node.classList.toggle('tick-off',!!body&&body.scrollHeight>body.clientHeight+1);}
  function bindTicks(node){if(!node)return;const ticks=()=>{node.querySelectorAll(TICKED).forEach(tapTick);tickRoom(node);};
    if(!boundTicks.has(node)){boundTicks.add(node);new MutationObserver(ticks).observe(node,{childList:true,subtree:true});}ticks();}
  addEventListener('resize',()=>{const top=overlays.at(-1);if(top&&top.id!==drawer.id&&$(top.id))tickRoom($(top.id));});
  function bindSheet(node){if(boundSheet.has(node))return;boundSheet.add(node);const box=node.querySelector('.box');if(!box)return;
    box.addEventListener('touchstart',e=>{sheetDrag=null;if(e.touches.length!==1||overlays.at(-1)?.id!==node.id||!isPhoneSheet(node))return;const t=e.touches[0],target=e.target;
      if(target.closest?.('input:not(.tap-tick),textarea,select,[contenteditable]'))return;
      if(!target.closest?.('.sh-head'))for(let p=target;p&&p!==node;p=p.parentElement)if(p.scrollTop>0)return;
      sheetDrag={node,box,x:t.clientX,y:t.clientY,dy:0,decided:false,h:box.offsetHeight||1};track(sheetDrag,t.clientX,t.clientY);},{passive:true});
    box.addEventListener('touchmove',e=>{const s=sheetDrag;if(!s||s.box!==box)return;if(e.touches.length!==1){endSheet(false);return;}const t=e.touches[0],dx=t.clientX-s.x,dy=t.clientY-s.y;
      if(!s.decided){if(Math.hypot(dx,dy)<6)return;if(!(dy>0&&dy>1.2*Math.abs(dx)&&e.cancelable)){sheetDrag=null;return;}s.decided=true;box.style.transition='none';node.style.transition='none';}
      e.preventDefault();track(s,t.clientX,t.clientY);s.dy=Math.max(0,dy);cancelAnimationFrame(frame);
      frame=requestAnimationFrame(()=>{if(sheetDrag!==s)return;box.style.transform=`translate3d(0,${s.dy}px,0)`;node.style.backgroundColor=`rgba(29,35,48,${(.22*(1-s.dy/s.h)).toFixed(3)})`;});
    },{passive:false});
    box.addEventListener('touchend',()=>endSheet(true));box.addEventListener('touchcancel',()=>endSheet(false));
  }
  function endSheet(allow){
    const s=sheetDrag;sheetDrag=null;cancelAnimationFrame(frame);if(!s?.decided)return;const {node,box,h}=s,v=speed(s,2),close=allow&&v>=-.3&&(s.dy>Math.min(160,h*.3)||v>.5);
    const ms=settleMs(close?h-s.dy:s.dy,h,close?v:-v);box.style.transform=`translate3d(0,${s.dy}px,0)`;box.offsetWidth;
    box.style.transition=ms?`transform ${ms}ms ${EASE}`:'none';node.style.transition=ms?`background-color ${ms}ms ${EASE}`:'none';
    box.style.transform=close?'translate3d(0,100%,0)':'translate3d(0,0,0)';node.style.backgroundColor=`rgba(29,35,48,${close?0:.22})`;
    if(close&&overlays.some(o=>o.id===node.id)){sheetPlanned=ms;closeSheet(node.id);sheetPlanned=null;}
    clearTimeout(node._sheetClear);node._sheetClear=setTimeout(()=>sheetClear(node),ms+(close?120:50));
  }
  // How long hideOverlay waits before display:none, so the drawer and sheets finish sliding first.
  function closeDelay(id){if(reduced())return 0;if(id===drawer.id)return (nav.planned??FULL)+100;if(isPhoneSheet($(id)))return (sheetPlanned??280)+40;return 160;}

  // ------------------------------------------------------------------ a sheet steps the page back
  // When a bottom sheet comes up on a phone, what is behind it (the chat; or the list, with the drawer if it shows) shrinks
  // a little towards the middle of the screen, as iOS does under its sheets, and comes back as the sheet goes. The list is
  // several separate parts: each gets the screen's middle as its own centre, so together they move as one picture. The
  // separate scale property adds to the drawer's and the chat's own transforms; its transition is set here with
  // !important because those parts carry inline transitions of their own. Not with Reduce Motion.
  let receded=[],recedeTimer=0;
  const rcss=el('style');rcss.textContent='.lbr-recede-move{transition:scale .46s '+EASE+'!important}.lbr-receded{scale:.94}';document.head.append(rcss);
  function recede(on){
    if(on===receded.length>0)return;
    clearTimeout(recedeTimer);
    if(!on){
      const was=receded;receded=[];was.forEach(n=>n.classList.remove('lbr-receded'));
      recedeTimer=setTimeout(()=>{if(!receded.length)was.forEach(n=>{n.classList.remove('lbr-recede-move');n.style.transformOrigin='';});},520);return;
    }
    if(reduced()||!animOK())return;
    const parts=cur?[view]:[...pageNodes(),...(drawer.style.display==='block'?[drawerBox]:[])],cx=innerWidth/2,cy=innerHeight/2;
    for(const n of parts){
      const r=n.getBoundingClientRect();let m={m41:0,m42:0};
      try{const t=getComputedStyle(n).transform;if(t&&t!=='none')m=new DOMMatrixReadOnly(t);}catch(e){}
      n.style.transformOrigin=`${cx-(r.left-m.m41)}px ${cy-(r.top-m.m42)}px`;n.classList.add('lbr-recede-move');
    }
    receded=parts;requestAnimationFrame(()=>{if(receded===parts)parts.forEach(n=>n.classList.add('lbr-receded'));});
  }

  function sync(){
    document.body.classList.toggle('chat-open',!!cur);document.body.classList.toggle('has-overlay',!!overlays.length);
    const topSheet=overlays.length?$(overlays.at(-1).id):null;recede(!!topSheet&&isPhoneSheet(topSheet));
    document.documentElement.style.setProperty('--chat-top',view.style.top||'0px');document.documentElement.style.setProperty('--chat-height',view.style.height||'100dvh');
    for(const n of pageNodes())bindPage(n);
    const open=overlays.some(o=>o.id===drawer.id);if(open!==nav.open){nav.open=open;navToggled(open);}
    if(drawer.style.display==='block')navLock(); // syncInert has just set body overflow back to hidden
    const top=overlays.at(-1)?.id||null;if(top!==lastTop){lastTop=top;const node=top&&$(top);if(node&&node!==drawer)bindTicks(node);if(node?.matches?.(SHEET)){clearTimeout(node._sheetClear);sheetClear(node);bindSheet(node);}}
  }
  window.addEventListener('pageshow',()=>{busy=false;reset();fitView();sync();syncInert();if(cur){readingUI?.resumeStream();loadConv(false);}});
  window.addEventListener('pagehide',()=>{reset();workspaceUI?.saveScene();readingUI?.pauseStream();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)reset();else{fitView();sync();}});
  window.addEventListener('resize',()=>{if(nav.open&&!drag){nav.n=N();drawerBox.style.width=nav.n+'px';strip.style.left=nav.n+'px';strip.style.width=Math.max(0,innerWidth-nav.n)+'px';navPaint(nav.n,0);}});
  window.navigationUI={onOpen,onClose,sync,back,pop,closeDelay,haptic,tapTick,tapLabel,openFromDrawer};sync();
})();

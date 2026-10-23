/* Packaged in Android only. No automatic mount and no browser APK capability. */
(() => {
  if(window.TeleplyAbout)return;
  let action=null,observer=null;
  function place(){
    const panel=document.getElementById('settingsBody')||document.querySelector('.theme-settings-panel');
    if(!panel)return false;
    let button=panel.querySelector('[data-native-about]');
    if(!button){button=document.createElement('button');button.type='button';button.className='menu-row text-button';button.dataset.nativeAbout='true';button.textContent='关于遥应';button.style.color='inherit';button.style.transition='background-color .15s';button.style.width='100%';button.style.minHeight='44px';button.style.textAlign='left';button.style.marginTop='12px';panel.append(button);}
    button.onclick=()=>{if(typeof action==='function')action();else if(typeof action==='string'&&action.startsWith('teleply-app://about?document='))location.assign(action);};
    return true;
  }
  window.TeleplyAbout={mount(value){action=value;if(place())return;if(observer)observer.disconnect();observer=new MutationObserver(()=>{if(place()){observer.disconnect();observer=null;}});observer.observe(document.documentElement,{childList:true,subtree:true});}};
})();

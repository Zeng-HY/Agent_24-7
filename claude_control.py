"""Controls on the existing Claude desktop session, with exact URL and fresh-option guards."""
from __future__ import annotations
import hashlib,json,re,secrets,threading,time
from datetime import datetime,timezone
from pathlib import Path
from app_paths import DATA
from urllib.parse import urlsplit
import chats
import winctl
try:
    from _ctypes import COMError  # what UI Automation raises through comtypes
except ImportError:  # pragma: no cover - not Windows
    class COMError(Exception):pass

# UIA_E_ELEMENTNOTAVAILABLE: the control was there a moment ago and Claude has drawn it anew or closed it (a menu
# closing after a pick, the effort button after a model switch). Windows names the same number 事件无法调用任何订户, and
# the phone showed that line as it was when the catalogue was refreshed after a switch to Sonnet (10-14).
GONE=-2147220991


def plain_error(exc):
    """What the phone is told about exc: a ChatError as it is; a COM error from reading Claude's window in words."""
    if isinstance(exc,COMError):
        code=exc.args[0] if exc.args else None
        if code==GONE:return '电脑上的 Claude 界面正好在重画，这次没读到，请再试一次'
        return f'电脑上的 Claude 界面没有响应（错误码 {code}），请再试一次'
    return str(exc)


class NextGone(chats.ChatError):
    """An app button of a next-step box with no button on the desktop to press it by: left to the PC (10-16)."""
    code='next_gone'

MODE_BUTTONS=('Auto','Plan','Manual','Ask','Ask permissions','Accept edits')  # the mode button by the message box shows the current mode
# Modes the phone may pick: Plan, Manual (Ask) and Auto, which runs on its own but stops to ask when something looks
# unsafe; it is what the user's sessions run in, and a pick of Plan on the phone could not be undone there (10-12).
# Never Skip all approvals / Bypass permissions, which do not stop even for unsafe actions. The menu names a mode
# with its description after it: 'Manual Always ask before making changes'.
MODE_CHOICES=re.compile(r'^(Plan|Manual|Auto|Ask(?: permissions)?)(?:\b|\s)',re.I)
MODES_VERSION=2  # remembered mode lists from before Auto could be picked are read again from the desktop
MODE_NOTICE='Plan 先出计划，确认后再改；Manual 每次改动前都先问你；Auto 自己做，遇到看起来不安全的操作才停下来问。'
EFFORT_LABELS=('Low','Medium','High','Extra','Max','Ultracode')


def model_label(name):
    """Ignore the new menu's Preset decoration and the combined button's effort suffix."""
    name=re.sub(r'^Model:\s*','',name or '').strip()
    name=re.sub(r'\s+Preset$','',name)
    return re.sub(r'\s+(?:Low|Medium|High|Extra|Max|Ultracode)(?:\s+.*)?$','',name)


def effort_label(name):
    match=re.search(r'\b(Low|Medium|High|Extra|Max|Ultracode)\b',name or '')
    return match[1] if match else None


def mode_word(name):
    """'Auto Recommended Claude handles permission decisions' -> 'auto': the part of a mode's name that stays the same."""
    return (name or '').split()[0].lower() if (name or '').strip() else ''


def load_modes(path):
    """The mode choices last read from the desktop menu, or [] when none were kept since Auto was allowed."""
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return []
    return data.get('modes') or [] if isinstance(data,dict) and data.get('version')==MODES_VERSION else []


def settings(item):
    for root in chats.claude_index_dirs():
        for path in root.glob('*/*/'+item['id']+'.json'):
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('sessionId')!=item['id']:continue
                return {'model':data.get('model'),'effort':data.get('effort'),'mode':data.get('permissionMode'),
                        'recorded_at':int(path.stat().st_mtime*1000)}
            except (OSError,ValueError):continue
    return {'model':None,'effort':None,'mode':None,'recorded_at':None}


def tokens(n,suffix):return round(float(n.replace(',',''))*{'':1,'k':1000,'m':1000000}[suffix.lower()])


def usage_from_label(label):
    match=re.search(r'Context\s+([\d.]+)([kKmM]?)\s*/\s*([\d.]+)([kKmM]?)\s*\(([\d.]+)%\)',label)
    if not match:return None
    used,window=tokens(match[1],match[2]),tokens(match[3],match[4])
    if window<=0:return None
    return {'used_tokens':used,'context_window':window,'percent':float(match[5]),'context_state':'available',
            'usage_time':datetime.now(timezone.utc).isoformat(),'source':'desktop','approximate':True}


def usage_from_context(texts):
    """The texts of the Context card in Claude's session panel (10-26, the dframe window): '53% used', then '526k / 1M',
    this conversation's context and its window, then one row per part (Messages 420.9k 42.1%, MCP tools 18.5k 1.9% …)
    that add up to the 526k. 'N tokens' stands for the pair when no window is shown. Since that window the Usage button
    by the model names the plan's weekly use ('Usage: Weekly · all models: 48%, Resets Sat 3:00 PM'), not the context."""
    percent=used=window=None
    for text in texts:
        text=(text or '').strip()
        if percent is None and (match:=re.fullmatch(r'<?\s*(\d+(?:\.\d+)?)\s*%\s+used',text,re.I)):percent=float(match[1])
        elif window is None and (match:=re.fullmatch(r'(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\s*/\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)',text)):
            if tokens(match[3],match[4])>0:used,window=tokens(match[1],match[2]),tokens(match[3],match[4])
        elif used is None and (match:=re.fullmatch(r'(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)\s+tokens',text,re.I)):used=tokens(match[1],match[2])
    if percent is None and used is not None and window:percent=round(used/window*100,1)
    if percent is None and used is None:return None
    return {'used_tokens':used,'context_window':window,'percent':percent,'context_state':'available' if percent is not None else 'partial',
            'usage_time':datetime.now(timezone.utc).isoformat(),'source':'desktop','approximate':True}


def signature(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]


def turn_anchor(path):
    if not path:return None
    for raw in reversed(chats.read_tail(path,2<<20)[0]):
        try:data=json.loads(raw)
        except ValueError:continue
        if data.get('type')!='user' or data.get('isSidechain') or data.get('isMeta'):continue
        content=(data.get('message') or {}).get('content')
        if isinstance(content,str) or (isinstance(content,list) and any(b.get('type') in ('text','image') for b in content if isinstance(b,dict))):return data.get('uuid')
    return None


def pending_questions(path):
    """The questions of the AskUserQuestion Claude waits on, as its call gave them (each with its 'multiSelect'): the
    newest such call in the record with no result yet. None when none waits or the record does not say."""
    if not path:return None
    asked=None
    for raw in chats.read_tail(path,2<<20)[0]:
        if b'AskUserQuestion' not in raw and b'tool_result' not in raw:continue
        try:data=json.loads(raw)
        except ValueError:continue
        content=(data.get('message') or {}).get('content') if isinstance(data,dict) else None
        for block in content if isinstance(content,list) else []:
            if not isinstance(block,dict):continue
            if block.get('type')=='tool_use' and block.get('name')=='AskUserQuestion':
                asked=(block.get('id'),(block.get('input') or {}).get('questions'))
            elif block.get('type')=='tool_result' and asked and block.get('tool_use_id')==asked[0]:
                asked=None
    return asked[1] if asked and isinstance(asked[1],list) else None


class Controller:
    def __init__(self,desktop):
        self.desktop=desktop;self.cache={};self.choices={};self.lock=threading.RLock();self.menu_context=None;self.steer_submissions={}
        from claude_archive import SessionActions
        self.session_actions = SessionActions(self)
        self.catalog_path=DATA/'attachments'/'claude-catalog.json'
        try:self.catalogs=json.loads(self.catalog_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.catalogs={}
        # The mode choices last read from the desktop menu, so the phone lists them at once (10-11); the menu
        # itself is opened only to apply a pick.
        self.modes_path=self.catalog_path.with_name('claude-modes.json')
        self.modes=load_modes(self.modes_path)
        self.hooks=None  # claude_hooks.Bridge, set by remote.py: questions and permissions Claude Code holds open (10-27)
        self.windows={}  # conversation -> the context window its Context card last showed (0.6.6)
    def _document(self,item,open_first=False):
        d=self.desktop
        if open_first:
            # Reopening an already-visible deep link can asynchronously destroy the just-opened menu.
            try:return self._document(item,False)
            except chats.ChatError:d._claude_open(item,[item['title'],chats.conversation_title(item)])
        hwnd,root=d._claude_root()
        doc=root.DocumentControl(searchDepth=18,Compare=lambda c,depth:(c.Name or '').endswith(' - Claude Code'))
        if not doc.Exists(.3,.1):raise chats.ChatError('电脑上没有打开 Claude Code 会话')
        value=d._value(doc)
        if not value.startswith('https://claude.ai/'):
            try:value=doc.GetLegacyIAccessiblePattern().Value or ''
            except Exception:pass
        try:matched=urlsplit(value).path.rstrip('/').split('/')[-1]==item['id']
        except ValueError:matched=False
        if not matched:raise chats.ChatError('电脑上显示的不是此 Claude 会话；请点击「电脑上打开」')
        return hwnd,root,doc
    def _walk(self,node,depth=40,offscreen=False):
        for ctrl,_ in self.desktop.auto.WalkControl(node,maxDepth=depth):
            try:
                if offscreen or not ctrl.IsOffscreen:yield ctrl
            except Exception:continue
    @staticmethod
    def _enabled(ctrl):
        try:return bool(ctrl.IsEnabled)
        except Exception:return False
    @staticmethod
    def _invoke(ctrl):
        # No coordinate fallback: the selected semantic control must still exist.
        for getter,method in [('GetInvokePattern','Invoke'),('GetSelectionItemPattern','Select'),
                              ('GetLegacyIAccessiblePattern','DoDefaultAction'),('GetTogglePattern','Toggle')]:
            try:pattern=getattr(ctrl,getter)()
            except Exception:continue
            if pattern is None:continue
            try:
                if getattr(pattern,method)() is False:raise RuntimeError('action returned false')
                return
            except Exception as exc:
                # A supported action may have happened before its response failed. Do not click twice.
                raise chats.ChatError('桌面操作结果未确认，请刷新查看；未重复点击') from exc
        raise chats.ChatError('这个桌面控件无法可靠操作，请在电脑上处理')
    @staticmethod
    def _expand(ctrl,opened):
        try:pattern=ctrl.GetExpandCollapsePattern()
        except Exception:pattern=None
        if pattern is None:return Controller._invoke(ctrl)
        try:
            desired=1 if opened else 0
            if pattern.ExpandCollapseState!=desired:
                if (pattern.Expand if opened else pattern.Collapse)() is False:raise RuntimeError('expand/collapse returned false')
        except Exception as exc:raise chats.ChatError('桌面菜单操作结果未确认，请刷新查看') from exc
    def _buttons(self,doc,every=None):
        """The page's visible buttons in page order, from one query: 0.06 s where walking the page took 0.45 s (10-12).
        every: that query's answer when the caller already has it."""
        out=[]
        for ctrl in self.desktop._find(doc,'ButtonControl') if every is None else every:
            try:
                if not ctrl.IsOffscreen:out.append(ctrl)
            except Exception:continue
        return out
    @staticmethod
    def _waiting_tasks(every):
        """The titles of the task cards Claude proposed that still wait on the desktop (10-16), scrolled into view or not:
        each has a cross named 'Dismiss suggestion <title>', gone once the task is started, done here or dismissed."""
        out=[]
        for ctrl in every:
            try:name=(ctrl.Name or '').strip()
            except Exception:continue
            if name.startswith('Dismiss suggestion '):out.append(name[len('Dismiss suggestion '):])
        return out
    def _context(self,doc):
        """This conversation's context from the Context card in the panel beside it (Session details, 10-26), read whether
        scrolled into view or not; None while that panel is closed or the card folded, and on any doubt (two such cards)."""
        try:
            cards=[c for c in self.desktop._find(doc,'GroupControl','Context') if self._inside(c,'Session details')]
            if len(cards)!=1:return None
            return usage_from_context([c.Name for c in self.desktop._find(cards[0],'TextControl')])
        except COMError:return None  # drawn anew while read: the next read, 5 s on, has it
    @staticmethod
    def _inside(ctrl,name,levels=5):
        for _ in range(levels):
            ctrl=ctrl.GetParentControl()
            if ctrl is None:return False
            if (ctrl.Name or '')==name:return True
        return False
    def _queued(self,doc,buttons=None):
        # buttons: the document's buttons when the caller already walked it (a walk costs ~0.8 s in a long chat)
        out=[]
        for button in (buttons if buttons is not None else self._buttons(doc)):
            if button.Name!='Send now' or not self._enabled(button):continue
            parent=button.GetParentControl()
            for _ in range(5):
                if re.fullmatch(r'Message \d+',parent.Name or ''):break
                parent=parent.GetParentControl()
            else:continue
            texts=[]
            for node in self._walk(parent,18):
                if node.ControlTypeName=='TextControl':
                    text=(node.Name or '').strip()
                    if text and not text.startswith('You said:') and text not in texts:texts.append(text)
            content='\n'.join(texts)
            if len(texts)>1 and texts[0].casefold() in ('unread','queued','waiting'):content='\n'.join(texts[1:])
            if not content:continue
            identity=signature([button.GetRuntimeId(),parent.Name,content])
            out.append((button,{'id':identity,'text':content[:4000],'full_text':content}))
        return out
    OPTION_TYPES=('ButtonControl','RadioButtonControl','CheckBoxControl')
    # The question card of Claude's new window (10-26) has arrows at its top as well: back is the only way back there;
    # forward only looks at the next question unanswered, which its Next does too.
    PROMPT_NAV={'Back':'上一题','Previous':'上一题','Show previous question':'上一题','Skip':'跳过','Next':'下一题','Submit':'提交',
                'Dismiss question':'不回答'}
    PROMPT_HIDDEN={'View question options','Show next question'}
    @staticmethod
    def _pressed(ctrl):
        for getter,attr in (('GetTogglePattern','ToggleState'),('GetSelectionItemPattern','IsSelected')):
            try:
                pattern=getattr(ctrl,getter)()
                if pattern is not None:value=getattr(pattern,attr);return bool(value) if attr=='IsSelected' else value==1
            except Exception:continue
        return None
    def _action_state(self,item):
        """The dock and its action revision exactly as _read computes them (the visible options + the transcript stamp),
        read from the dock alone: a full _read walks the whole conversation first and took ~2.3 s (1.35 s now)."""
        _,root,doc=self._document(item);dock=self.desktop._claude_ask(root,doc)
        options,_=self._dock_read(dock) if dock else ([],None)
        path=chats.conv_path(item);stamp=(path.stat().st_size,path.stat().st_mtime_ns) if path else None
        return signature([item['id'],options,stamp]),dock
    @staticmethod
    def _toggled(ctrl):
        try:return ctrl.GetTogglePattern().ToggleState
        except Exception:return None
    def _single_choice(self,item,card):
        """Whether the question on this card takes one choice: True, False for several, None when the record's pending
        AskUserQuestion has no question of the card's text."""
        try:title=chats.norm(card.Name or '')
        except Exception:return None
        for question in pending_questions(chats.conv_path(item)) or []:
            if isinstance(question,dict) and chats.norm(question.get('question') or '')==title:
                return not question.get('multiSelect')
        return None
    def _pick(self,item,card,option):
        """An option of a question card in Claude's new window, picked with a real click (chats.Desktop._click_control):
        UI Automation's press only moved the focus to it (10-27 08:19). A question that takes one choice then goes on
        with the card's Next, or Submit on the last question, as one tap on an option did in Claude's old window and as
        the phone apps expect; with several choices each tap picks one more, and Submit stays the phone's to tap.
        Returns the name of the button pressed after the pick, or ''."""
        d=self.desktop;hwnd=self._document(item)[0];name=(option.Name or '').strip()
        single=self._single_choice(item,card);was=self._toggled(option)
        before=d._keyboard_owner()
        def fresh():  # read anew each time: so the pick showed within 0.08 s on 10-27 09:39
            try:return next((c for c in d._find(card,'ButtonControl') if (c.Name or '').strip()==name),option)
            except Exception:return option
        try:
            d._click_control(hwnd,option)
            deadline=time.monotonic()+1.5
            while True:  # Claude marks the pick a moment later; nothing goes on before it shows
                now=self._toggled(fresh())
                if (now==1) if single else (now!=was or (single is None and now==1)):break
                if time.monotonic()>=deadline:raise chats.ChatError('电脑上没有选上这一项，没有往下走；请在电脑上选')
                time.sleep(.1)
            if not single:return ''
            go=next((c for c in self._walk(card,30,offscreen=True) if c.ControlTypeName=='ButtonControl'
                     and (c.Name or '').strip() in ('Next','Submit') and self._enabled(c)),None)
            if go is None:return ''
            went=(go.Name or '').strip();shown=card.Name
            self._invoke(go)
            deadline=time.monotonic()+1.5
            while time.monotonic()<deadline:  # the next question, or the card gone, before the state is read again
                try:
                    if card.Name!=shown:break
                except Exception:break
                time.sleep(.1)
            return went
        finally:d._give_back_keyboard(before)
    def _dock_read(self,dock):
        """One pass over the dock below the conversation. Returns the clickable options exactly as before (their list
        and the transcript stamp make the action revision) and, for the phone, the prompt above the message box laid
        out: question text, progress such as '1 / 2', each choice as label + description, and the navigation.
        10-11 recording of a question (AskUserQuestion): texts '1' '/' '2' and the question; one button per option
        named 'label description N' holding a label text, a description text and the shortcut digit; 'Other N' with
        an 'Other option' field; 'Skip' / 'Next'; 'View question options' and 'Dismiss question' in the header.
        dock may also be a question card of Claude's new window (chats.question_card, recorded 10-26): the question,
        'Show previous question', a text '1 of 2', 'Show next question', one button per option named 'label description'
        holding the two texts, 'Other', 'Skip' / 'Next'. It sits among the messages, so it is read scrolled out of
        view as well."""
        card=chats.question_card(dock)
        options,buttons,texts,stack,box_top=[],[],[],[],None
        rows=list(self.desktop.auto.WalkControl(dock,maxDepth=30))
        attachment_names=set()
        for ctrl,_ in rows:
            try:
                if ctrl.ControlTypeName=='ButtonControl' and (ctrl.Name or '').startswith('Remove '):attachment_names.add(ctrl.Name[7:])
            except COMError:continue
        for ctrl,depth in rows:
            try:kind=ctrl.ControlTypeName;name=(ctrl.Name or '').strip();off=ctrl.IsOffscreen
            except Exception:continue
            del stack[max(depth-1,0):];stack.append((kind,name))
            if off and not card:continue
            if kind=='EditControl' and name=='Prompt':
                try:box_top=ctrl.BoundingRectangle.top
                except Exception:pass
                continue
            try:top=ctrl.BoundingRectangle.top
            except Exception:top=None
            if chats.in_notice([k for k,_ in stack[:-1]]):continue  # a notice bar (the usage limit, 10-16), not a question
            if kind in self.OPTION_TYPES:
                if not name or not self._enabled(ctrl):continue
                if name in attachment_names or name in chats.CLAUDE_FIXED_BUTTONS or name.startswith(chats.CLAUDE_FIXED_PREFIXES) or name in ('Plan','Manual','Ask','Ask permissions','Accept edits'):continue
                option={'type':kind,'name':name};options.append(option);buttons.append({'option':option,'top':top,'texts':[],'pressed':self._pressed(ctrl)})
            elif kind=='TextControl' and name:
                if name.startswith('Claude thinks longer with Max effort'):continue
                owner=next((s for s in reversed(stack[:-1]) if s[0] in self.OPTION_TYPES),None)
                if owner is None:texts.append((top,name))
                else:
                    held=next((b for b in reversed(buttons) if b['option']['name']==owner[1]),None)
                    if held is not None:held['texts'].append(name)
        above=lambda top:box_top is None or top is None or top<box_top  # the prompt sits above the message box
        panel=[b for b in buttons if above(b['top'])];words=[name for top,name in texts if above(top)]
        if not panel:return options,None
        marks=[w for w in words if re.fullmatch(r'\d+|/',w)]
        counter=next((w for w in words if re.fullmatch(r'\d+ of \d+',w)),None)  # the card's one text '1 of 2'
        progress=counter.replace(' of ',' / ') if counter else ' '.join(marks[:3]) if len(marks)>=3 else None
        prompt={'title':'\n'.join(w for w in words if not re.fullmatch(r'\d+|/|\d+ of \d+',w)),'progress':progress,
                'choices':[],'nav':[],'other':None}
        for b in panel:
            name=b['option']['name']
            if name in self.PROMPT_HIDDEN:continue
            if name in self.PROMPT_NAV:prompt['nav'].append({'name':name,'label':self.PROMPT_NAV[name]});continue
            if re.fullmatch(r'Other(\s+\d+)?',name):prompt['other']={'name':name};continue
            parts=[t for t in b['texts'] if not re.fullmatch(r'\d+',t)]
            prompt['choices'].append({'name':name,'label':parts[0] if parts else re.sub(r'\s+\d+$','',name),'description':'\n'.join(parts[1:]),'pressed':b['pressed']})
        return options,prompt
    def _new_page(self,hwnd):
        """(hwnd, root, document) of Claude's page for a new session, checked to be that page (raises if not)."""
        root=self.desktop._need_auto().ControlFromHandle(hwnd)
        doc,_=self.desktop._claude_verified_prompt(root,'__new__')
        return hwnd,root,doc
    def _dismiss_popup(self,item,page=None):
        # page: (hwnd, root, doc) of the new-session page, where there is no conversation to look up yet
        hwnd,root,doc=page or self._document(item)
        try:
            popup=root.MenuControl(searchDepth=85)
            if not popup.Exists(.2,.1) or popup.IsOffscreen:
                popup=root.WindowControl(Name='Effort',searchDepth=85)
            if not popup.Exists(.2,.1) or popup.IsOffscreen:return
        except COMError:return  # it closed while being looked at: nothing to dismiss
        popup_name=popup.Name or ''
        prefix='Model: ' if popup_name.startswith(('Model: ','Effort ')) else 'Effort: ' if popup_name=='Effort' else None
        if prefix:
            triggers=[c for c in self._buttons(doc) if (c.Name or '').startswith(prefix)]
            if len(triggers)==1:
                self._expand(triggers[0],False)
                return
        # Escape only while a verified popup belongs to this exact session, never in its composer.
        with self.desktop.input_lock:
            winctl.focus(hwnd)
            if page:self._new_page(hwnd)
            else:self._document(item)
            try:
                if popup.IsOffscreen:return
            except COMError:return
            winctl.press(hwnd,'Escape')
        time.sleep(.15)
    def _again(self,read,*args):
        """read(*args), and once more after a moment when Claude drew a control anew under it (COMError). Only for reads
        and for opening a menu, which a second try finds open already; never around a click."""
        try:return read(*args)
        except COMError:
            time.sleep(.5)
            return read(*args)
    def _read(self,item):
        try:return self._again(self._read_once,item)
        except COMError as exc:  # twice in a row: say so, the phone reads again in 5 s
            return {'settings':settings(item),'available':False,'on_screen':False,'actions':[],'reason':plain_error(exc),
                    'observed_at':int(time.time()*1000),'mode_options':self.modes}
    def _read_once(self,item):
        # The phone open on a Claude conversation reads this every 5 s. Minimised, the window does not update what is read
        # here (questions, Stop); it is restored first, without being made active or put over other windows (10-12).
        try:self.desktop._claude_unminimize()
        except Exception:pass
        recorded=settings(item);path=chats.conv_path(item);runtime=chats.runtime_info('claude',path) if path else {}
        # The model and effort the session's record names go with every read, the desktop's context only when it is read
        # (10-26: the context was not read, and the effort the phone shows went missing with it).
        model,effort=recorded.get('model') or runtime.get('model'),recorded.get('effort')
        if model or effort:runtime={**runtime,'model':model,'effort':effort}
        result={'settings':recorded,'runtime':runtime,'available':False,'on_screen':False,'actions':[],
                'observed_at':int(time.time()*1000),'mode_options':self.modes,'recorded_label':self._model_name(recorded.get('model'))}
        try:
            _,root,doc=self._document(item);every=self.desktop._find(doc,'ButtonControl');buttons=self._buttons(doc,every);names=[(c.Name or '').strip() for c in buttons]
            result['tasks']=self._waiting_tasks(every)
            model_name=next((n for n in names if n.startswith('Model: ')),None)
            model=model_label(model_name) if model_name else None
            effort=next((n[8:] for n in names if n.startswith('Effort: ')),None) or effort_label(model_name)
            usage=next((u for u in (usage_from_label(n) for n in names if n.startswith('Usage: ')) if u),None) or self._context(doc)
            result.update(available=bool(model),on_screen=True,model_label=model,effort_label=effort,running='Stop' in names or chats.summary(item).get('status')=='running',
                          mode_label=next((n.removeprefix('Permissions: ') for n in names if n in MODE_BUTTONS or n.startswith('Permissions: ')),None))
            if not model:
                # Report the actual blocking UI instead of claiming that a setting was applied.
                visible=[(c.Name or '').strip() for c in self._walk(root,75) if c.ControlTypeName in ('WindowControl','ButtonControl')]
                result['reason']='Claude 桌面正在等待模型切换确认，请在电脑上处理。' if 'Switch model' in visible else 'Claude 设置控件暂不可用，请检查电脑上的会话或弹窗。'
            anchor=turn_anchor(path)
            result['turn_anchor']=anchor;result['queued']=[]
            for _,queued in self._queued(doc,buttons):
                revision=signature([item['id'],anchor,queued['id']])
                result['queued'].append({'id':queued['id'],'text':queued['text'],'token':self._ticket(item['id'],'steer_queued',{'id':queued['id']},revision)})
            if result['running'] and anchor:
                result['stop_revision']=signature([item['id'],anchor]);result['stop_token']=self._ticket(item['id'],'stop',{'name':'Stop'},result['stop_revision'])
            if usage:
                result['runtime']={**runtime,**usage}
                if usage.get('context_window'):self.windows[item['id']]=usage['context_window']
            elif runtime.get('context_state')=='partial' and runtime.get('used_tokens') is not None and self.windows.get(item['id']):
                # 0.6.6: the Context card is closed: the record's count over the window last read off it, so a
                # /compact's postTokens moves the ring at once
                window=self.windows[item['id']]
                result['runtime']={**runtime,'context_window':window,'percent':round(runtime['used_tokens']/window*100,1),
                                   'context_state':'available','approximate':True}
            dock=self.desktop._claude_ask(root,doc)  # a question card of Claude's new window, or the dock (10-26)
            options,prompt=self._dock_read(dock) if dock else ([],None)
            # Bind execution/answer buttons to both the visible set and the latest transcript version.
            stamp=(path.stat().st_size,path.stat().st_mtime_ns) if path else None
            result['action_revision']=signature([item['id'],options,stamp])
            for option in options[:30]:
                result['actions'].append({**option,'token':self._ticket(item['id'],'action',option,result['action_revision'])})
            if prompt:  # the same buttons, laid out for the phone; each part carries its action's token
                tokens={a['name']:a['token'] for a in result['actions']}
                for part in prompt['choices']+prompt['nav']+([prompt['other']] if prompt['other'] else []):part['token']=tokens.get(part['name'])
                result['prompt']=prompt
                # and only so: both phone apps drew the actions too, as a second card of raw button names under the
                # question (iPhone 10-26 23:09: 计划与执行选项, Show previous question, 选项丙 随便选…); the web shows
                # actions only when there is no prompt
                result['actions']=[]
        except chats.ChatError as exc:result['reason']=str(exc)
        return result
    def _model_name(self,model_id):
        """The menu's name for a recorded model id ('Opus 5.5' for claude-opus-5-5), from a catalogue read on the PC
        before: the phone shows the model and its effort without the PC showing the conversation (10-12)."""
        for catalog in reversed(list(self.catalogs.values())):
            if isinstance(catalog,dict) and model_id and catalog.get('model_id')==model_id:
                name=next((o.get('name') for o in catalog.get('model') or [] if o.get('selected')),None)
                if name:return name
        return None
    def state(self,tid,fresh=False):
        with self.lock:
            old=self.cache.get(tid)
            if not fresh and old and time.monotonic()-old[0]<4:return self._held(tid,old[1])
            item=chats.find('claude',tid)
            try:data=self.desktop.run(self._read,item,timeout=12)
            except Exception as exc:data={'available':False,'reason':plain_error(exc),'settings':settings(item),'actions':[]}
            try:
                info=chats.summary(item)
                data={**data,'turn_started':info.get('turn_started',0),'turn_ended':info.get('turn_ended',0),
                      'step':info.get('step','') if data.get('running') else ''}
            except (OSError,chats.ChatError):pass
            self.cache[tid]=(time.monotonic(),data)
            if len(self.cache)>20:self.cache.pop(next(iter(self.cache)))
            return self._held(tid,data)
    def _held(self,tid,data):
        """data with the question or permission Claude Code holds open for this conversation (claude_hooks.py) as its
        prompt, in place of what was read off the desktop's card: answered from here, nothing on the desktop is clicked,
        and shown whichever conversation the PC shows (10-27)."""
        hooks=self.hooks
        if hooks is None:return data
        held=hooks.layout(tid)
        if held is None:
            # the desktop may still draw the card a phone answer has just closed: not offered as a question again
            return {**data,'prompt':None,'actions':[]} if hooks.just_answered(tid) and (data.get('prompt') or data.get('actions')) else data
        ask_id,prompt,stamp=held
        for part in prompt['choices']+prompt['nav']:
            do=part.pop('do');ready=part.pop('ready',True)
            part['token']=self._ticket(tid,'hook',{'ask':ask_id,'do':do},stamp) if ready else None
        return {**data,'prompt':prompt,'actions':[]}
    def _ticket(self,tid,kind,option,revision):
        now=time.monotonic()
        self.choices={k:v for k,v in self.choices.items() if now-v['created']<120}
        for token,value in self.choices.items():
            if value['id']==tid and value['kind']==kind and value['option']==option and value['revision']==revision and now-value['created']<60:return token
        token=secrets.token_hex(16);self.choices[token]={'id':tid,'kind':kind,'option':option,'revision':revision,'created':now}
        return token
    def _menu(self,item,kind,page=None):
        # page: the new-session page as _new_page gives it, instead of the conversation item names (10-14)
        if kind not in ('model','effort','mode','fast'):raise chats.ChatError('未知设置项')
        hwnd,root,doc=page or self._document(item,True)
        self.desktop._claude_show(hwnd)  # a minimised window draws no menu and reads stale (10-12)
        if self.menu_context and self.menu_context!=(item['id'],kind):
            if self.menu_context[0]==item['id']:self._dismiss_popup(item,page)
            self.menu_context=None
            hwnd,root,doc=self._new_page(hwnd) if page else self._document(item)
        buttons=self._buttons(doc)
        combined=kind=='effort' and not any((c.Name or '').startswith('Effort: ') for c in buttons) and any(effort_label(c.Name) for c in buttons if (c.Name or '').startswith('Model: '))
        match=lambda c:(c.Name or '').startswith('Model: ') if kind in ('model','fast') or combined else (c.Name or '').startswith('Effort: ') if kind=='effort' else ((c.Name or '') in MODE_BUTTONS or (c.Name or '').startswith('Permissions: '))
        triggers=[c for c in buttons if match(c)]
        # A pick made on the phone while the PC showed another conversation switches the PC first (10-12); the
        # buttons by the message box are drawn a moment after the page itself.
        deadline=time.monotonic()+6
        while (len(triggers)!=1 or not self._enabled(triggers[0])) and time.monotonic()<deadline:
            time.sleep(.25);buttons=self._buttons(doc);triggers=[c for c in buttons if match(c)]
        if len(triggers)!=1 or not self._enabled(triggers[0]):raise chats.ChatError('没有找到唯一可用的 Claude 设置按钮')
        menu=root.MenuControl(searchDepth=85)
        if menu.Exists(.2,.1):
            if self.menu_context!=(item['id'],kind):
                if self.menu_context and self.menu_context[0]==item['id']:
                    old=self.menu_context[1]
                    previous=[c for c in buttons if (c.Name or '').startswith('Model: ' if old in ('model','fast') else 'Effort: ') ] if old!='mode' else [c for c in buttons if (c.Name or '') in MODE_BUTTONS]
                    if len(previous)!=1:raise chats.ChatError('电脑上的菜单已变化，请关闭后重试')
                    self._dismiss_popup(item,page);time.sleep(.1);self._expand(triggers[0],True);self.menu_context=(item['id'],kind);time.sleep(.15)
                else:raise chats.ChatError('电脑上已有其他菜单，请先关闭后重试')
        else:
            self._expand(triggers[0],True);self.menu_context=(item['id'],kind);time.sleep(.15)
        if combined:
            entries=[c for c in self._walk(menu,18) if c.ControlTypeName=='MenuItemControl' and (c.Name or '').startswith('Effort ') and self._enabled(c)]
            if len(entries)!=1:raise chats.ChatError('Claude 模型菜单里没有唯一的推理强度入口')
            submenu=root.MenuControl(Name=entries[0].Name,searchDepth=95)
            if not submenu.Exists(.2,.1) or submenu.IsOffscreen:self._expand(entries[0],True)
            if not submenu.Exists(.3,.1) or submenu.IsOffscreen:
                # The current web menu can acknowledge UIA Expand without opening
                # its submenu. ArrowRight on the verified submenu trigger opens it.
                with self.desktop.input_lock:
                    winctl.focus(hwnd)
                    if page:self._new_page(hwnd)
                    else:self._document(item)
                    entries[0].SetFocus()
                    if not entries[0].HasKeyboardFocus:raise chats.ChatError('Claude 推理强度菜单焦点未核对')
                    winctl.press(hwnd,'ArrowRight')
            if not submenu.Exists(1,.1) or submenu.IsOffscreen:raise chats.ChatError('Claude 推理强度子菜单没有打开')
            menu=submenu
        if kind=='effort' and not combined:
            panel=root.WindowControl(Name='Effort',searchDepth=85)
            if panel.Exists(1,.1) and not panel.IsOffscreen:
                slider=panel.SliderControl(Name='Effort',searchDepth=15)
                if slider.Exists(.4,.1):
                    value=slider.GetRangeValuePattern()
                    if value and not value.IsReadOnly:
                        bounds={'min':value.Minimum,'max':value.Maximum,'step':value.SmallChange,'value':value.Value,'label':self.desktop._value(slider)}
                        model_id=item.get('model_id') or settings(item).get('model')  # the new page: the model just picked
                        key='labels:'+str(model_id)+':'+str((bounds['min'],bounds['max'],bounds['step']))
                        labels=self.catalogs.setdefault(key,{}) if model_id else {}
                        labels[str(int(bounds['value']))]=bounds['label']
                        bounds['labels']=dict(labels)
                        return [(slider,{'name':'Effort','type':'SliderControl','selected':True,'range':bounds})]
        if not menu.Exists(1,.1):
            raise chats.ChatError('桌面没有提供可读取的设置菜单，请在电脑上查看')
        choices=[]
        for ctrl in self._walk(menu,18):
            if ctrl.ControlTypeName not in ('MenuItemControl','RadioButtonControl','ListItemControl','CheckBoxControl','ButtonControl') or not self._enabled(ctrl):continue
            name=(ctrl.Name or '').strip()
            if not name:continue
            if kind=='fast' and not re.search(r'\bfast\b',name,re.I):continue
            if kind=='model' and re.search(r'\bfast\b',name,re.I):continue
            if kind!='fast' and ctrl.ControlTypeName in ('CheckBoxControl','ButtonControl'):continue
            if kind=='mode' and not MODE_CHOICES.match(name):continue  # Plan, Manual and Auto; never a blanket bypass
            selected=False
            selectable=False
            try:
                pattern=ctrl.GetSelectionItemPattern()
                if pattern is not None:selectable=True;selected=bool(pattern.IsSelected)
            except Exception:
                pass
            if not selectable:
                try:
                    pattern=ctrl.GetTogglePattern()
                    if pattern is not None:selectable=True;selected=bool(pattern.ToggleState)
                except Exception:pass
            if kind in ('model','fast') and not selectable:continue  # Submenu navigation is not a model selection.
            if kind=='model':
                if effort_label(name) and name.split()[0] in EFFORT_LABELS:continue
                name=model_label(name)
            if kind=='effort' and combined and not selectable:continue
            choices.append((ctrl,{'name':name,'type':ctrl.ControlTypeName,'selected':selected}))
        return choices
    def catalog(self,tid,fresh=False):
        """Cache display data only. Every mutation resolves a fresh native control."""
        with self.lock:
            item=chats.find('claude',tid);recorded=settings(item)
            cached=self.catalogs.get(tid)
            if cached and not fresh and cached.get('model_id')==recorded.get('model'):
                return {**cached,'cached':True}
            if not fresh:
                # Model capabilities can be shared across sessions; selection state cannot.
                reusable=next((v for v in reversed(list(self.catalogs.values())) if isinstance(v,dict) and v.get('model_id')==recorded.get('model') and v.get('model')),None)
                if reusable:
                    copy=json.loads(json.dumps(reusable));copy['cached']=True;copy['borrowed']=True
                    for option in copy.get('fast',[]):option['selected']=None
                    for option in copy.get('effort',[]):
                        option['selected']=False
                        if option.get('range'):option['range']['value']=None
                    return copy
            def run():
                result={'model_id':recorded.get('model'),'updated_at':int(time.time()*1000),'cached':False}
                for kind in ('model','effort','fast'):
                    try:result[kind]=[v for _,v in self._again(self._menu,item,kind)]
                    except (chats.ChatError,COMError) as exc:
                        if kind=='model':raise chats.ChatError(plain_error(exc)) from exc
                        result[kind]=[];result[kind+'_reason']=plain_error(exc)
                    finally:
                        self._dismiss_popup(item);self.menu_context=None
                return result
            result=self.desktop.run(run,timeout=35)
            result['model_id']=settings(item).get('model')
            self.catalogs[tid]=result
            self._save_catalogs()
            return result
    # -- a new conversation's model and effort (10-14: the new-conversation sheet had no way to pick them)
    def _model_id(self,name):
        """The model id behind a menu name: claude-<name> ('Sonnet 5.5' -> claude-sonnet-5-5, the form all four ids took on
        10-14), or a recorded id that holds that form with more to it. Not "the id of a session whose menu ticks it": a
        session's recorded id follows only once a message went out on the new model, and the one switched to Sonnet
        on 10-14 still said Opus."""
        slug=re.sub(r'[^a-z0-9]+','-',model_label(name).lower()).strip('-')
        known={v['model_id'] for v in self.catalogs.values() if isinstance(v,dict) and isinstance(v.get('model_id'),str)}
        return next((m for m in sorted(known) if slug and ('-'+slug) in m),'claude-'+slug)
    def new_options(self):
        """Models and effort steps for a new conversation, from what the PC's menus showed before. Effort is the slider's
        steps; a step whose name was never read on a model takes the name another model gave that step."""
        lists=[v for v in self.catalogs.values() if isinstance(v,dict) and v.get('model')]
        if not lists:return {'models':[],'note':'还没从电脑读到 Claude 的模型列表：在任一 Claude 对话里打开一次模型面板就有了'}
        maps={k:v for k,v in self.catalogs.items() if k.startswith('labels:') and isinstance(v,dict) and v}
        widest=max(maps.items(),key=lambda kv:len(kv[1]),default=(None,{}))
        def steps(key):
            try:low,high,step=(float(x) for x in key.rsplit(':',1)[1].strip('()').split(','))
            except (ValueError,IndexError):return []
            out,value=[],low
            while value<=high+1e-9 and step>0 and len(out)<20:out.append(int(value));value+=step
            return out
        models=[]
        for name in [model_label(m['name']) for m in lists[-1]['model']]:
            model_id=self._model_id(name);key=next((k for k in maps if k.startswith('labels:'+model_id+':')),None)
            own=maps.get(key,{});base=key or widest[0]
            efforts=[{'id':v,'label':own.get(str(v)) or widest[1].get(str(v)) or f'第 {v+1} 档'} for v in (steps(base) if base else [])]
            models.append({'id':name,'label':name,'model_id':model_id,'efforts':efforts,'default_effort':None})
        return {'models':models,'note':''}
    def _shows(self,hwnd,name,seconds=4):
        """The new-session page's buttons come to include one named name (the model button after a pick)."""
        deadline=time.monotonic()+seconds
        while True:
            try:
                if any((model_label(c.Name)==model_label(name) if name.startswith('Model: ') and (c.Name or '').startswith('Model: ') else (c.Name or '')==name) for c in self._buttons(self._new_page(hwnd)[2])):return True
            except COMError:pass
            if time.monotonic()>=deadline:return False
            time.sleep(.25)
    def apply_new(self,hwnd,model=None,effort=None):
        """On Claude's page for a new session, before its first message is written: the model, then the effort step the
        phone picked. Raises InputNotSubmitted when the page does not end up showing them: a first message on another
        model than the one picked is worse than one not sent yet (the phone keeps the draft and can send again)."""
        item={'id':'__new__','model_id':None}
        try:
            self._dismiss_popup(item,self._new_page(hwnd));self.menu_context=None
            if model:
                options=self._again(self._menu,item,'model',self._new_page(hwnd))
                hits=[(c,v) for c,v in options if model_label(v['name'])==model_label(model)]
                if len(hits)!=1:raise chats.InputNotSubmitted(f'Claude 新建页的模型菜单里没有「{model}」，首条消息未发送')
                if not hits[0][1]['selected']:self._invoke(hits[0][0])
                self._dismiss_popup(item,self._new_page(hwnd));self.menu_context=None
                if not self._shows(hwnd,'Model: '+model):raise chats.InputNotSubmitted(f'Claude 新建页没有换成「{model}」，首条消息未发送')
                item['model_id']=self._model_id(model)
            if effort is not None:
                page=self._new_page(hwnd)
                buttons=self._buttons(page[2])
                desired=EFFORT_LABELS[effort] if isinstance(effort,int) and not isinstance(effort,bool) and 0<=effort<len(EFFORT_LABELS) else str(effort)
                if any(effort_label(c.Name)==desired for c in buttons if (c.Name or '').startswith(('Model: ','Effort: '))):return
                if not any((c.Name or '').startswith('Effort: ') or (c.Name or '').startswith('Model: ') and effort_label(c.Name) for c in buttons):
                    raise chats.InputNotSubmitted('未能核对所选模型的推理强度控件，首条消息未发送')
                options=self._again(self._menu,item,'effort',page)
                if len(options)==1 and options[0][1].get('range'):
                    ctrl,v=options[0];bounds=v['range']
                    if isinstance(effort,bool) or not isinstance(effort,(int,float)) or not bounds['min']<=effort<=bounds['max']:
                        raise chats.InputNotSubmitted('推理强度档位不在 Claude 的范围里，首条消息未发送')
                    pattern=ctrl.GetRangeValuePattern()
                    if pattern.Value!=effort and pattern.SetValue(effort) is False:raise chats.InputNotSubmitted('Claude 的推理强度没设上，首条消息未发送')
                    time.sleep(.2)
                    if pattern.Value!=effort:raise chats.InputNotSubmitted('Claude 的推理强度没设上，首条消息未发送')
                    if item['model_id']:  # the step's name, learnt for this model
                        key='labels:'+item['model_id']+':'+str((bounds['min'],bounds['max'],bounds['step']))
                        self.catalogs.setdefault(key,{})[str(int(effort))]=self.desktop._value(ctrl)
                else:
                    # Existing phone drafts use the legacy slider's 0..5 values.
                    desired=EFFORT_LABELS[effort] if isinstance(effort,int) and not isinstance(effort,bool) and 0<=effort<len(EFFORT_LABELS) else str(effort)
                    hits=[(c,v) for c,v in options if effort_label(v['name'])==desired or v['name']==desired]
                    if len(hits)!=1:raise chats.InputNotSubmitted(f'Claude 新建页没有「{effort}」这一档推理强度，首条消息未发送')
                    if not hits[0][1]['selected']:self._invoke(hits[0][0])
                    self._dismiss_popup(item,self._new_page(hwnd));self.menu_context=None
                    deadline=time.monotonic()+4
                    while True:
                        shown=self._buttons(self._new_page(hwnd)[2])
                        if any(effort_label(c.Name)==desired for c in shown if (c.Name or '').startswith(('Model: ','Effort: '))):break
                        if time.monotonic()>=deadline:raise chats.InputNotSubmitted('Claude 推理强度切换尚未核对，首条消息未发送')
                        time.sleep(.2)
                self._dismiss_popup(item,self._new_page(hwnd));self.menu_context=None
        except COMError as exc:
            raise chats.InputNotSubmitted('Claude 新建页正好在重画，模型或推理强度没设上，首条消息未发送') from exc
        except (chats.ChatError,winctl.WinError) as exc:
            if isinstance(exc,chats.InputNotSubmitted):raise
            raise chats.InputNotSubmitted(str(exc)+'；首条消息尚未发送') from exc
        finally:
            self.menu_context=None;self._save_catalogs()
    def _save_catalogs(self):
        if len(self.catalogs)>30:self.catalogs.pop(next(iter(self.catalogs)))
        try:
            self.catalog_path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.catalog_path.with_suffix('.tmp');temp.write_text(json.dumps(self.catalogs,ensure_ascii=False),encoding='utf-8');temp.replace(self.catalog_path)
        except OSError:pass
    def _catalog_after_model(self,tid,cached,name,state,own=True):
        """After a model switch the list of models stays the same; only the tick moves, and the effort steps belong
        to the new model. They are taken from any session already on that model, or the effort panel alone is read.
        The phone used to ask for the whole catalogue again (model menu, effort panel, model menu once more for
        Fast), which showed on the PC as three more menus opening and closing right after the switch (10-12)."""
        item=chats.find('claude',tid);model_id=settings(item).get('model')
        fresh=json.loads(json.dumps(cached))
        for option in fresh.get('model',[]):option['selected']=option.get('name')==name
        if not own:  # another session's Fast switch says nothing about this one
            for option in fresh.get('fast',[]):option['selected']=None
        fresh.update(model_id=model_id,updated_at=int(time.time()*1000),cached=False);fresh.pop('borrowed',None)
        donor=next((v for k,v in reversed(list(self.catalogs.items())) if k!=tid and isinstance(v,dict) and v.get('model_id')==model_id and v.get('model')),None)
        if donor is not None:
            fresh['effort']=json.loads(json.dumps(donor.get('effort',[])))
            shown=re.sub(r'\s+\d+(?:\.\d+)?×.*$','',(state.get('effort_label') or '').strip())
            for option in fresh['effort']:
                bounds=option.get('range')
                if bounds:  # the slider position follows from the label on the effort button
                    hits=[int(v) for v,label in (bounds.get('labels') or {}).items() if re.sub(r'\s+\d+(?:\.\d+)?×.*$','',label)==shown]
                    bounds['value']=hits[0] if len(hits)==1 else None;bounds['label']=shown or bounds.get('label')
                else:option['selected']=option.get('name')==shown
            fresh.pop('effort_reason',None)
        else:
            def run():  # the effort button is drawn anew right after the switch: read it again if it went under us
                try:return [v for _,v in self._again(self._menu,item,'effort')]
                finally:self._dismiss_popup(item);self.menu_context=None
            try:fresh['effort']=self.desktop.run(run,timeout=40);fresh.pop('effort_reason',None)
            except (chats.ChatError,COMError) as exc:fresh['effort']=[];fresh['effort_reason']=plain_error(exc)
        self.catalogs[tid]=fresh;self._save_catalogs()
        return fresh
    def select_setting(self,tid,kind,name,value=None,expected_model=None):
        if kind not in ('model','effort','fast','mode'):raise chats.ChatError('未知设置项')
        with self.lock:
            if expected_model is not None and settings(chats.find('claude',tid)).get('model')!=expected_model:
                raise chats.ChatError('桌面模型已变化，请刷新选项后重选')
            menu=self.menu(tid,kind)
            # A mode is known by its first word: the rest changes with the mode in force. On 10-12 Auto read 'Auto Claude
            # handles permission decisions' while it was on and 'Auto Recommended Claude handles…' once Plan was, so the
            # phone's pick of Auto, named as last read, found no such entry and Plan could not be left.
            options=[v for v in menu['items'] if (mode_word(v['name'])==mode_word(name) if kind=='mode' else v['name']==name)]
            if len(options)!=1:
                if kind=='mode':self.close_menu(tid);raise chats.ChatError('电脑上的模式选项变了，列表已更新，请再选一次')
                raise chats.ChatError('选项已变化，请刷新模型目录')
            option=options[0]
            if kind=='mode' and option['selected']:
                self.close_menu(tid);return {'ok':True,'state':self.state(tid,True)}
            if kind=='fast' and (not isinstance(value,bool)):raise chats.ChatError('无效速度设置')
            if kind=='fast' and option['selected']==value:
                self.close_menu(tid);self.catalogs.pop(tid,None);return {'ok':True,'state':self.state(tid,True)}
            result=self.choose(tid,option['token'],value if kind=='effort' else None)
            if kind=='mode':return self._mode_applied(tid,name,result)
            if kind=='model':
                deadline=time.monotonic()+6
                while result.get('state',{}).get('model_label')!=name and time.monotonic()<deadline:
                    time.sleep(.3);result['state']=self.state(tid,True)
                if result.get('state',{}).get('model_label')!=name:
                    self.catalogs.pop(tid,None)
                    raise chats.ChatError('模型切换尚未核对，请查看桌面：'+result.get('state',{}).get('reason',''))
            if kind=='fast':
                observed=self.menu(tid,'fast');self.close_menu(tid)
                if len(observed['items'])!=1 or observed['items'][0]['selected']!=value:
                    self.catalogs.pop(tid,None)
                    raise chats.ChatError('Fast 状态未能核对，请刷新桌面目录')
            cached=self.catalogs.pop(tid,None)
            if kind=='model':  # the model list is the same in every session, so any stored catalogue can carry it
                base=cached or next((v for v in reversed(list(self.catalogs.values())) if isinstance(v,dict) and v.get('model')),None)
                if base:result['catalog']=self._catalog_after_model(tid,base,name,result.get('state') or {},own=cached is not None)
            if cached and kind in ('effort','fast'):
                # Update the existing catalog with the native readback, without reopening all menus.
                if kind=='effort' and option.get('range'):
                    label=result.get('state',{}).get('effort_label') or str(value)
                    label=re.sub(r'\s+\d+(?:\.\d+)?×.*$','',label)
                    option['range'].update(value=value,label=label)
                    option['range'].setdefault('labels',{})[str(int(value))]=label
                    cached['effort']=[{k:v for k,v in option.items() if k!='token'}]
                elif kind=='fast':cached['fast']=[{**{k:v for k,v in option.items() if k!='token'},'selected':value}]
                cached['updated_at']=int(time.time()*1000);self.catalogs[tid]=cached
                result['catalog']=cached
            return result
    def _mode_applied(self,tid,name,result):
        """The mode button by the message box names the mode in force; give it a moment to follow the pick."""
        first=lambda s:(s or '').split()[0].lower() if (s or '').strip() else ''
        deadline=time.monotonic()+3
        while (label:=result.get('state',{}).get('mode_label')) and first(label)!=first(name) and time.monotonic()<deadline:
            time.sleep(.3);result['state']=self.state(tid,True)
        label=result.get('state',{}).get('mode_label')
        if label and first(label)!=first(name):raise chats.ChatError('模式切换尚未核对，电脑上现在是「'+label+'」')
        return result
    def _remember_modes(self,modes):
        if modes==self.modes:return
        self.modes=modes
        try:
            temp=self.modes_path.with_suffix('.tmp');temp.parent.mkdir(parents=True,exist_ok=True)
            temp.write_text(json.dumps({'version':MODES_VERSION,'modes':modes},ensure_ascii=False),encoding='utf-8');temp.replace(self.modes_path)
        except OSError:pass
    def menu(self,tid,kind):
        with self.lock:
            item=chats.find('claude',tid)
            def run():
                options=self._again(self._menu,item,kind);rev=signature([{k:v for k,v in settings(item).items() if k!='recorded_at'},[v['name'] for _,v in options]])
                return {'items':[{**v,'token':self._ticket(tid,kind,v,rev)} for _,v in options],
                        'notice':'选择会直接应用到此 Claude 会话；当前正在运行的请求不保证立即改变。' if kind!='mode' else MODE_NOTICE}
            result=self.desktop.run(run,timeout=40)
            if kind=='mode':self._remember_modes([{'name':v['name'],'type':v['type']} for v in result['items']])
            return result
    def choose(self,tid,token,value=None):
        with self.lock:
            ticket=self.choices.pop(token,None)
            if not ticket or ticket['id']!=tid or time.monotonic()-ticket['created']>=120:raise chats.ChatError('选项已过期，请重新打开面板')
            if ticket['kind']=='hook':  # answered through the request Claude Code holds open; the desktop is not touched
                if self.hooks is None:raise chats.ChatError('选项已过期，请重新打开面板')
                text=self.hooks.press(tid,ticket['option']['ask'],ticket['option']['do'],ticket['revision'])
                self.cache.pop(tid,None)
                try:return {'ok':True,'text':text,'state':self.state(tid,True)}
                except Exception:return {'ok':True,'text':text}  # the answer went; the phone reads the state again itself
            item=chats.find('claude',tid)
            def run():
                dock=None;went=None;started=time.monotonic()
                if ticket['kind'] in ('steer_queued','stop','action'):  # what is clicked must be what Claude shows now
                    try:self.desktop._claude_show(self._document(item)[0])
                    except Exception:pass  # not on screen, or no window: the checks below say so
                if ticket['kind']=='steer_queued':
                    _,_,doc=self._document(item)
                    anchor=turn_anchor(chats.conv_path(item));queue=self._queued(doc)
                    targets=[button for button,q in queue if q['id']==ticket['option']['id'] and signature([tid,anchor,q['id']])==ticket['revision']]
                elif ticket['kind']=='stop':
                    current=self._read(item)
                    if not current.get('running') or current.get('stop_revision')!=ticket['revision']:raise chats.ChatError('该轮已经结束或进入下一轮，未执行停止')
                    _,_,doc=self._document(item);targets=[c for c in self._buttons(doc) if c.Name=='Stop' and self._enabled(c)]
                elif ticket['kind']=='action':
                    revision,dock=self._action_state(item)
                    if revision!=ticket['revision']:raise chats.ChatError('计划或执行选项已变化，未执行旧选项')
                    targets=[c for c in self._walk(dock,30,offscreen=chats.question_card(dock)) if c.ControlTypeName==ticket['option']['type'] and (c.Name or '').strip()==ticket['option']['name']] if dock else []
                else:
                    options=self._again(self._menu,item,ticket['kind']);rev=signature([{k:v for k,v in settings(item).items() if k!='recorded_at'},[v['name'] for _,v in options]])
                    if rev!=ticket['revision']:raise chats.ChatError('模型或菜单已变化，请重新选择')
                    targets=[c for c,v in options if v['name']==ticket['option']['name'] and v['type']==ticket['option']['type']]
                if len(targets)!=1:raise chats.ChatError('选项已变化或不唯一，没有执行')
                if ticket['option'].get('range'):
                    bounds=ticket['option']['range'];pattern=targets[0].GetRangeValuePattern()
                    if isinstance(value,bool) or not isinstance(value,(int,float)) or not bounds['min']<=value<=bounds['max'] or bounds['step']<=0 or abs((value-bounds['min'])/bounds['step']-round((value-bounds['min'])/bounds['step']))>1e-6:raise chats.ChatError('无效的推理强度档位')
                    if pattern.Value!=bounds['value'] or pattern.Minimum!=bounds['min'] or pattern.Maximum!=bounds['max']:raise chats.ChatError('强度已经变化，请刷新后重选')
                    if pattern.SetValue(value) is False:raise chats.ChatError('强度操作结果未确认，请刷新查看')
                    time.sleep(.2);self._dismiss_popup(item)
                elif chats.question_card(dock) and chats.answer_option(targets[0]):
                    label=chats.one_line(ticket['option']['name'],30)
                    try:went=self._pick(item,dock,targets[0])
                    except chats.ChatError as exc:
                        self.desktop.log(f"Claude「{item['title']}」：手机上选「{label}」没选上（{time.monotonic()-started:.1f} 秒）：{exc}")
                        raise
                    after={'Next':'，并点了「下一题」','Submit':'，并点了「提交」'}.get(went,'')
                    self.desktop.log(f"Claude「{item['title']}」：手机上选了「{label}」{after}（{time.monotonic()-started:.1f} 秒）")
                else:
                    self._invoke(targets[0])
                    if ticket['kind'] in ('model','effort','mode','fast'):self._dismiss_popup(item)
                self.menu_context=None;time.sleep(.3)
                text={'Next':'已在电脑上选好，并点了「下一题」','Submit':'已在电脑上选好并提交'}.get(went,'已在电脑上选好' if went=='' else None)
                return {'ok':True,'text':text or ('已请求立即补充，等待 Claude 读取' if ticket['kind']=='steer_queued' else '已操作，下面显示重新读取的桌面状态'),'state':self._held(tid,self._read(item))}
            try:return self.desktop.run(run,timeout=40)
            finally:self.cache.pop(tid,None)
    def _next_box(self,doc,box):
        """The next-step box on the desktop that asks what this box from the record asks: ('buttons', its buttons in order)
        while it takes a click, ('list', []) when the desktop draws it as text with its choices as a plain list, None when
        it is not there (yet). Recorded 10-16, both at the end of the chat, not in the dock (so the phone's options never
        held either): at 10:00 a group with the recap, Dismiss, the question and a group 'Suggested next actions' with the
        buttons, named as their labels; at 12:40 the recap, the question and a list, one item per label, nothing to click
        (that turn also proposed a task). Read whether scrolled into view or not."""
        walk=self.desktop.auto.WalkControl;groups=self.desktop._find(doc,'GroupControl','Suggested next actions')
        for group in reversed(groups):
            try:
                texts={chats.norm(c.Name or '') for c,_ in walk(group.GetParentControl(),maxDepth=4) if c.ControlTypeName=='TextControl'}
                if box['ask'] and chats.norm(box['ask']) not in texts:continue
                return 'buttons',[c for c,_ in walk(group,maxDepth=3) if c.ControlTypeName=='ButtonControl' and self._enabled(c)]
            except COMError:continue
        for text in reversed(self.desktop._find(doc,'TextControl',box['ask'])) if box['ask'] else []:
            try:
                row=text.GetParentControl().GetParentControl()
                if [(c.Name or '').strip() for c,_ in walk(row,maxDepth=3) if c.ControlTypeName=='ListItemControl']==[a['label'] for a in box['actions']]:
                    return 'list',[]
            except COMError:continue
        return ('other',[]) if groups else None  # a box that asks something else: the PC and the record disagree
    def next_step(self,tid,tool_id,index,label):
        """A button of the next-step box that ends a Claude turn (10-16), as if clicked on the desktop. Only while the
        record's open box is this one (the same call) with this button. The desktop's box that asks the same question with
        as many buttons gets the same one pressed (a reply button must bear this label there too; an app button shows the
        app's own label). With no button there to press (drawn as a plain list, or no longer shown), a reply button's words
        go as a message, which is all its click does; an app button is left to the PC."""
        with self.lock:
            item=chats.find('claude',tid);box=chats.claude_open_next(item)
            if not box or box['tool_id']!=tool_id:raise chats.ChatError('这个框已经不在了：回复过了，或者已经是新的一轮。刷新看看')
            if not 0<=index<len(box['actions']) or box['actions'][index]['label']!=label:raise chats.ChatError('框里的按钮变了，刷新后再点')
            action=box['actions'][index]
            def run():
                hwnd,_,_=self._document(item,True)  # the PC opens this conversation first when it shows another
                try:self.desktop._claude_show(hwnd)
                except Exception:pass
                deadline=time.monotonic()+8
                while True:  # a long conversation draws its end last
                    found=self._next_box(self._document(item)[2],box)
                    if found is not None or time.monotonic()>=deadline:break
                    time.sleep(.3)
                if found and found[0]=='other':raise chats.ChatError('电脑上的框问的已经是别的问题了，没有点；刷新看看')
                if found and found[0]=='buttons':
                    buttons=found[1]
                    if len(buttons)!=len(box['actions']) or ('action' not in action and (buttons[index].Name or '').strip()!=label):
                        raise chats.ChatError('电脑上框里的按钮和记录里的对不上，没有点；请在电脑上处理')
                    self._invoke(buttons[index])
                    self.desktop.log(f"Claude「{item['title']}」：下一步点了「{label}」")
                    return {'ok':True,'text':f'已在电脑上点了「{label}」'}
                if 'action' in action:raise NextGone(f'电脑上这个框现在点不了，「{label}」请在电脑上操作')
                self.desktop.send('claude',tid,action['message'])  # it checks the conversation and the message box itself
                return {'ok':True,'sent':True,'text':f'电脑上这个框没有按钮，已把「{label}」要说的话发过去'}
            try:return self.desktop.run(run,timeout=60)
            finally:self.cache.pop(tid,None)
    TASK_BUTTONS={'start':'Start','here':'Do it here','dismiss':None}  # None: the card's cross, named for its title
    def _task_buttons(self,doc,title,name):
        """The buttons named name on the task cards titled title: in the card, beside the button that bears the title.
        Recorded 10-16: a group '1 suggested task' holding the text 'New session', a button named as the title, a cross
        'Dismiss suggestion <title>', and Options, Do it here and Start."""
        out=[]
        for head in self.desktop._find(doc,'ButtonControl',title):
            try:out+=[c for c,_ in self.desktop.auto.WalkControl(head.GetParentControl(),maxDepth=1)
                      if c.ControlTypeName=='ButtonControl' and (c.Name or '').strip()==name and self._enabled(c)]
            except COMError:continue
        return out
    def task_step(self,tid,title,button):
        """Start, Do it here or the cross of a task card Claude proposed (10-16), pressed on the card on the desktop that
        bears this very title; one only, and only while it still waits there."""
        if button not in self.TASK_BUTTONS or not title.strip():raise chats.ChatError('没有这个操作')
        name=self.TASK_BUTTONS[button] or 'Dismiss suggestion '+title
        with self.lock:
            item=chats.find('claude',tid)
            def run():
                hwnd,_,_=self._document(item,True)
                try:self.desktop._claude_show(hwnd)
                except Exception:pass
                deadline=time.monotonic()+8
                while True:
                    targets=self._task_buttons(self._document(item)[2],title,name)
                    if targets or time.monotonic()>=deadline:break
                    time.sleep(.3)
                if len(targets)!=1:raise chats.ChatError('电脑上有几张同名的任务卡片，没有点；请在电脑上处理' if targets else '电脑上这张任务卡片已经处理过了，或者不在了')
                self._invoke(targets[0])
                done={'start':'开始了','here':'点了「Do it here」','dismiss':'关掉了'}[button]
                self.desktop.log(f"Claude「{item['title']}」：任务卡片「{title}」{done}")
                return {'ok':True,'text':'已在电脑上'+done+('，新对话会出现在列表里' if button=='start' else '')}
            try:return self.desktop.run(run,timeout=60)
            finally:self.cache.pop(tid,None)
    def close_menu(self,tid):
        with self.lock:
            if not self.menu_context or self.menu_context[0]!=tid:return {'ok':True}
            item=chats.find('claude',tid)
            self.desktop.run(self._dismiss_popup,item,timeout=12);self.menu_context=None;return {'ok':True}

    def send_steer(self,tid,text,expected_anchor,request_id):
        """Submit once, then promote only the newly observed exact-text queued item."""
        with self.lock:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{12,80}',request_id):raise chats.InputNotSubmitted('无效补充请求编号，尚未发送')
            fingerprint=signature([tid,text,expected_anchor]);previous=self.steer_submissions.get(request_id)
            if previous:
                if previous['fingerprint']!=fingerprint:raise chats.ChatError('请求编号已用于其他消息')
                if previous.get('result'):return previous['result']
                raise chats.ChatError('这条补充指令已有提交记录，尚未确认，不会重复发送')
            item=chats.find('claude',tid);text=chats.clean_text(text)
            def run():
                state=self._read(item)
                if not state.get('on_screen') or not state.get('running') or not expected_anchor or state.get('turn_anchor')!=expected_anchor:
                    raise chats.InputNotSubmitted('Claude 当前轮次已变化或未打开该会话，尚未发送补充指令')
                _,_,doc=self._document(item);before={q['id'] for _,q in self._queued(doc)}
                self.steer_submissions[request_id]={'fingerprint':fingerprint}
                result=self.desktop.send('claude',tid,text)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    try:
                        _,_,doc=self._document(item);candidates=[(b,q) for b,q in self._queued(doc) if q['id'] not in before and chats.norm(q['full_text'])==chats.norm(text)]
                        if len(candidates)==1:
                            self._invoke(candidates[0][0]);return {**result,'steer_requested':True,'text':'已提交补充指令并请求立即读取'}
                        if len(candidates)>1:break
                        if chats.Desktop.check('claude',tid,result['offset'],text)['delivered']:
                            return {**result,'steer_requested':True,'text':'补充指令已进入 Claude 的输入记录'}
                    except Exception:break
                    time.sleep(.15)
                return {**result,'steer_requested':False,'text':'消息已提交，立即读取状态尚未确认；不会重复发送'}
            try:
                result=self.desktop.run(run,timeout=60)
                self.steer_submissions[request_id]={'fingerprint':fingerprint,'result':result}
                return result
            except chats.SendNotSubmitted:
                self.steer_submissions.pop(request_id,None);raise
            finally:self.cache.pop(tid,None)

import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from message_files import absolute_links, references
import chat_history

class RelativeLinkTests(unittest.TestCase):
    """10-27: Claude's desktop app has Claude link files relative to its folder; phones opened only full paths."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name in ('dist/AgentRemote-Setup.exe','apps/x.kt','中文 文件 (1).md','a_b.md'):
            (self.root/name).parent.mkdir(parents=True,exist_ok=True);(self.root/name).write_text('x',encoding='utf-8')
        self.base=str(self.root).replace('\\','/')

    def test_links_to_existing_files_become_full_paths(self):
        text=('[安装包](dist/AgentRemote-Setup.exe)、[x.kt:42](apps/x.kt:42)、[文档](<中文 文件 (1).md>)、'
              '[转义](a\\_b.md) 和 ![图](apps/x.kt "标题")')
        out=absolute_links(text,str(self.root))
        self.assertEqual(out,'[安装包](<{0}/dist/AgentRemote-Setup.exe>)、[x.kt:42](<{0}/apps/x.kt:42>)、'
                             '[文档](<{0}/中文 文件 (1).md>)、[转义](<{0}/a_b.md>) 和 ![图](<{0}/apps/x.kt> "标题")'.format(self.base))
        self.assertEqual(references(out),[self.base+'/dist/AgentRemote-Setup.exe',self.base+'/apps/x.kt',
                                          self.base+'/中文 文件 (1).md',self.base+'/a_b.md',self.base+'/apps/x.kt'])

    def test_everything_else_stays_as_written(self):
        text=('[没有](missing.md) [网页](https://example.com/a.md) [锚点](#top) [邮件](mailto:a@b.c) [根](/etc/x) '
              '[完整](D:/x/y.md) `[代码](dist/AgentRemote-Setup.exe)`\n\n```\n[围栏](dist/AgentRemote-Setup.exe)\n```\n'
              '    [缩进](dist/AgentRemote-Setup.exe)\n')
        self.assertEqual(absolute_links(text,str(self.root)),text)
        self.assertEqual(absolute_links('[a](dist/AgentRemote-Setup.exe)',''),'[a](dist/AgentRemote-Setup.exe)')
        self.assertEqual(absolute_links('[a](dist/AgentRemote-Setup.exe)','relative/folder'),'[a](dist/AgentRemote-Setup.exe)')

    def test_a_link_beside_code_that_names_it_is_still_rewritten(self):
        text='`dist/AgentRemote-Setup.exe` 在这里：[打开](dist/AgentRemote-Setup.exe)'
        self.assertEqual(absolute_links(text,str(self.root)),
                         '`dist/AgentRemote-Setup.exe` 在这里：[打开](<'+self.base+'/dist/AgentRemote-Setup.exe>)')

    def test_claude_record_lists_the_file_and_sends_the_full_path(self):
        line={'type':'assistant','uuid':'u1','timestamp':'2026-10-27T13:00:00Z',
              'message':{'role':'assistant','stop_reason':'end_turn','content':[{'type':'text','text':'在 [这里](dist/AgentRemote-Setup.exe)。'}]}}
        record=self.root/'record.jsonl';record.write_text(json.dumps(line,ensure_ascii=False)+'\n',encoding='utf-8')
        entry=chat_history.Transcript(record,'claude',str(self.root)).refresh()
        self.assertEqual(entry.messages[-1]['text'],'在 [这里](<'+self.base+'/dist/AgentRemote-Setup.exe>)。')
        codex=chat_history.Transcript(record,'codex',str(self.root))
        self.assertEqual(codex.cwd,str(self.root))  # Codex keeps its text: its copies are matched by their words

if __name__=='__main__':
    unittest.main()

import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import voice_terms
import voice_local

DICTIONARY='Claude = cloud\nChatGPT = catGPT\nCodex\nOpenAI\nGPT\nGemini\n飞书\n搜狗\nTM\n'

class CopiedDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();path=Path(self.temp.name)/'voice_terms.txt';path.write_text(DICTIONARY,encoding='utf-8')
        self.terms=patch.object(voice_terms,'TERMS_FILE',path);self.terms.start();voice_terms._cache['key']=None
    def tearDown(self):self.terms.stop();voice_terms._cache['key']=None;self.temp.cleanup()
    def test_the_list_written_out_instead_of_the_word(self):
        # 10-12 20:41: "Codex 提问的提示条和面板" came out as the first three words of the dictionary
        self.assertEqual(voice_terms.copied_run('Claude ChatGPT Codex 提问的提示条和面板。','col提问的提示条和面板。'),['Claude','ChatGPT','Codex'])
    def test_the_whole_list_with_other_separators(self):
        text='Claude ChatGPT、Codex、OpenAI、GPT、Gemini、飞书、搜狗、TM。'  # a laugh, 10-12 21:38
        self.assertEqual(len(voice_terms.copied_run(text,'哈哈哈')),9)
    def test_words_said_apart_out_of_order_or_heard_stay(self):
        self.assertEqual(voice_terms.copied_run('Claude 和 ChatGPT 都试过','Claude 和 ChatGPT 都试过'),[])  # not one after another
        self.assertEqual(voice_terms.copied_run('ChatGPT Claude 都行',''),[])                             # not in the list's order
        self.assertEqual(voice_terms.copied_run('我用 Claude ChatGPT 比较','我用 Claude ChatGPT 比较'),[])    # the fast model heard them
        self.assertEqual(voice_terms.copied_run('Codex 提问的提示条','col提问的提示条'),[])                  # one word is no list
        self.assertEqual(voice_terms.copied_run('ChatGPT',''),[])                                        # GPT inside ChatGPT is not a second word
    def test_a_copied_stretch_is_recognised_again_without_the_dictionary(self):
        asr=object.__new__(voice_local.LocalASR);asr.plain=object()
        heard={False:'Claude ChatGPT Codex 提问的提示条和面板。',True:'Codex提问的提示条和面板。'}
        asr._recognize_accurate=lambda samples,plain=False:heard[plain]
        self.assertEqual(asr._accurate_text([0.0],'col提问的提示条和面板。'),('Codex提问的提示条和面板。',True))
        heard[False]='Codex提问的提示条和面板。'  # nothing copied: the dictionary model's text stands
        self.assertEqual(asr._accurate_text([0.0],'col提问的提示条和面板。'),('Codex提问的提示条和面板。',False))
        heard[False]='Claude ChatGPT Codex 提问的提示条和面板。';asr.plain=None  # without the second model nothing else to ask
        self.assertEqual(asr._accurate_text([0.0],'col提问的提示条和面板。'),('Claude ChatGPT Codex 提问的提示条和面板。',False))

if __name__=='__main__':unittest.main()

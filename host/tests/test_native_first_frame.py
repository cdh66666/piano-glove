"""Desktop stylesheet ordering prevents the legacy debug first frame."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_window

class StyleLocations(HTMLParser):
    def __init__(self):
        super().__init__(); self.head=False; self.styles=[]
    def handle_starttag(self,tag,attrs):
        if tag=='head': self.head=True
        if tag=='style': self.styles.append(self.head)
    def handle_endtag(self,tag):
        if tag=='head': self.head=False

class FirstFrameTests(unittest.TestCase):
    def test_all_bundled_style_nodes_precede_body(self):
        for page in native_window.PAGES:
            with self.subTest(page=page):
                rendered=native_window.render_page(page)
                parsed=StyleLocations();parsed.feed(rendered)
                self.assertTrue(parsed.styles)
                self.assertTrue(all(parsed.styles))
                self.assertNotIn('<link rel="stylesheet"',rendered)
    def test_debug_waits_for_current_layout_before_reveal(self):
        rendered=native_window.render_page('debug')
        self.assertIn('<html class="native-preparing"',rendered)
        self.assertIn('html.native-preparing body>*{visibility:hidden!important}',rendered)
        self.assertIn("body.dataset.desktopDebug='ready';document.documentElement.classList.remove('native-preparing')",rendered)
        self.assertLess(rendered.index('html.native-preparing body>*'),rendered.index('<body'))
        self.assertIn('bootBack.style.setProperty("visibility","visible","important")',rendered)

if __name__=='__main__':unittest.main()

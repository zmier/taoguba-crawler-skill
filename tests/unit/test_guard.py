import unittest

from common.tgb_guard import AntiBotBlocked, GuardDecision, classify_tgb_page, require_normal_page


ERROR_HTML = """
<!DOCTYPE HTML>
<html>
  <head><title>错误页面_淘股吧</title></head>
  <body>访问太频繁，请稍后再试</body>
</html>
"""


ARTICLE_HTML = """
<html>
  <body>
    <div id="stockTitle">正常帖子</div>
    <div class="article-text p_coten" id="first">正文</div>
  </body>
</html>
"""


class TestTgbGuard(unittest.TestCase):
    def test_classify_error_page_as_blocked(self):
        # GIVEN：一个淘股吧错误页 HTML
        html = ERROR_HTML

        # WHEN：分类页面
        decision = classify_tgb_page(html, expected="article")

        # THEN：应识别为 blocked，而不是正常详情页
        self.assertEqual(decision, GuardDecision.BLOCKED)

    def test_classify_article_page_as_normal(self):
        # GIVEN：一个包含帖子标题和正文结构的 HTML
        html = ARTICLE_HTML

        # WHEN：分类页面
        decision = classify_tgb_page(html, expected="article")

        # THEN：应识别为 normal
        self.assertEqual(decision, GuardDecision.NORMAL)

    def test_require_normal_page_raises_on_blocked_page(self):
        # GIVEN：一个错误页 HTML
        html = ERROR_HTML

        # WHEN / THEN：要求正常页面时应抛出反爬熔断异常
        with self.assertRaises(AntiBotBlocked):
            require_normal_page(html, url="https://www.tgb.cn/a/blocked", expected="article")


if __name__ == "__main__":
    unittest.main()

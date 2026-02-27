from .issue_detector import IssueDetector
from .issue_prioritizer import IssuePrioritizer

class AutoSEOEngine:

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def run(self, url: str):

        data = {
            "title": "",
            "meta_description": "",
            "word_count": 0,
            "internal_links": []
        }

        issues = IssueDetector().detect(data)
        prioritized = IssuePrioritizer().prioritize(issues)

        return {
            "url": url,
            "issues": prioritized,
            "message": "Auto SEO Engine placeholder (crawler not active)"
        }

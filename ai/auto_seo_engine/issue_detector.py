class IssueDetector:

    def detect(self, data: dict):

        issues = []

        title = data.get("title", "")
        meta = data.get("meta_description", "")
        word_count = data.get("word_count", 0)

        if not title:
            issues.append({
                "type": "missing_title",
                "severity": "critical",
                "penalty": 20,
                "message": "Title is missing"
            })

        if len(title) < 30:
            issues.append({
                "type": "short_title",
                "severity": "high",
                "penalty": 10,
                "message": "Title should be 30+ characters"
            })

        if not meta:
            issues.append({
                "type": "missing_meta",
                "severity": "critical",
                "penalty": 20,
                "message": "Meta description missing"
            })

        if word_count < 300:
            issues.append({
                "type": "thin_content",
                "severity": "medium",
                "penalty": 15,
                "message": "Content is thin (<300 words)"
            })

        return issues

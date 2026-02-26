def analyze_seo(data: dict):
    score = 100
    issues = []

    title = data.get("title", "").strip()
    meta = data.get("meta_description", "").strip()

    if not title:
        score -= 20
        issues.append("Missing title")

    if len(title) < 30:
        score -= 10
        issues.append("Title too short (recommended 30+ characters)")

    if not meta:
        score -= 20
        issues.append("Missing meta description")

    if meta and len(meta) < 70:
        score -= 10
        issues.append("Meta description too short (recommended 70+ characters)")

    return {
        "seo_score": max(score, 0),
        "issues": issues
    }

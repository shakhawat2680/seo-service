def analyze_seo(data: dict):
    score = 100
    issues = []

    if not data.get("title"):
        score -= 20
        issues.append("Missing title")

    if not data.get("meta_description"):
        score -= 20
        issues.append("Missing meta description")

    return {
        "seo_score": score,
        "issues": issues
    }

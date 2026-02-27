class OpportunityDetector:

    def detect(self, data: dict):

        opportunities = []

        word_count = data.get("word_count", 0)
        internal_links = data.get("internal_links", [])

        if word_count > 800:
            opportunities.append({
                "type": "pillar_content",
                "score": 20,
                "message": "Good candidate for pillar content strategy"
            })

        if len(internal_links) < 5:
            opportunities.append({
                "type": "internal_linking",
                "score": 15,
                "message": "Add internal links to strengthen SEO"
            })

        return opportunities

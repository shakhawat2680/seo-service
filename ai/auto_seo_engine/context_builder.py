class ContextBuilder:

    def build(self, raw: dict):

        return {
            "url": raw.get("url"),
            "title": raw.get("title"),
            "meta_description": raw.get("meta_description"),
            "h1": raw.get("h1"),
            "word_count": raw.get("word_count"),
            "internal_links": raw.get("internal_links"),
            "semantic_entities": raw.get("entities", [])
        }

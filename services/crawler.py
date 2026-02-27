import requests
from bs4 import BeautifulSoup

def crawl_page(url: str):
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")

    return {
        "title": soup.title.string if soup.title else "",
        "meta_description": "",
        "word_count": len(soup.get_text().split()),
        "internal_links": []
    }

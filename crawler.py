import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
from typing import List, Dict

class Crawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'AutoSEO Bot/1.0'
        })
        self.visited = set()
        self.results = []
    
    def crawl(self, start_url: str, max_pages: int = 50) -> List[Dict]:
        """Crawl website and return pages"""
        self.visited.clear()
        self.results.clear()
        
        to_visit = {start_url}
        domain = urlparse(start_url).netloc
        
        while to_visit and len(self.results) < max_pages:
            url = to_visit.pop()
            if url in self.visited:
                continue
            
            self.visited.add(url)
            
            try:
                response = self.session.get(url, timeout=10)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                page = {
                    'url': url,
                    'title': self._get_title(soup),
                    'meta_description': self._get_meta_description(soup),
                    'h1': self._get_headings(soup, 'h1'),
                    'h2': self._get_headings(soup, 'h2'),
                    'images': self._get_images(soup, url),
                    'links': self._get_links(soup, url, domain),
                    'word_count': len(soup.get_text().split()),
                    'load_time': response.elapsed.total_seconds() * 1000,
                    'status_code': response.status_code
                }
                
                self.results.append(page)
                
                for link in page['links']:
                    if link['internal'] and link['url'] not in self.visited:
                        to_visit.add(link['url'])
                
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error crawling {url}: {e}")
                continue
        
        return self.results
    
    def _get_title(self, soup):
        title = soup.find('title')
        return title.string.strip() if title and title.string else None
    
    def _get_meta_description(self, soup):
        meta = soup.find('meta', attrs={'name': 'description'})
        return meta['content'].strip() if meta and meta.get('content') else None
    
    def _get_headings(self, soup, tag):
        return [h.get_text(strip=True) for h in soup.find_all(tag)]
    
    def _get_images(self, soup, base_url):
        images = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                images.append({
                    'src': urljoin(base_url, src),
                    'alt': img.get('alt', ''),
                    'has_alt': bool(img.get('alt'))
                })
        return images
    
    def _get_links(self, soup, base_url, domain):
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                full_url = urljoin(base_url, href)
                links.append({
                    'url': full_url,
                    'text': a.get_text(strip=True)[:100],
                    'internal': urlparse(full_url).netloc == domain
                })
        return links

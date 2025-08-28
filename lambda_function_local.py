#lokal versiyon
import json
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime, timezone
import logging
import warnings
from dateutil import parser as date_parser
import os

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Logger ayarları - konsol çıktısı için
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Lokal dosya ayarları
OUTPUT_FOLDER = "scraped_news"  # Çıktı klasörü
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

# Google News RSS URLs
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}


def is_within_last_hour(published_date_str):
    """Verilen tarih string'inin son 1 saat içinde olup olmadığını kontrol eder."""
    if not published_date_str:
        return False
        
    try:
        # RSS tarih formatını parse et
        pub_date = date_parser.parse(published_date_str)
        
        # Timezone bilgisi yoksa UTC varsay
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        # Şu anki zaman (UTC)
        now_utc = datetime.now(timezone.utc)
        
        # Son 1 saat = 3600 saniye
        time_diff = (now_utc - pub_date).total_seconds()
        
        return 0 <= time_diff <= 3600
        
    except Exception as e:
        logger.warning(f"Tarih parse hatası: {e}")
        return False


def scrape_category(category_name, rss_url):
    """Belirli bir haber kategorisinden RSS beslemesini çeker ve son 1 saatteki haberleri filtreler."""
    scraped_articles = []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        logger.info(f"Kategori çekiliyor: {category_name}")
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.find_all('item', limit=20)
        
        for index, item in enumerate(items):
            try:
                # Başlık işleme
                title_element = item.find('title')
                if not title_element:
                    continue
                    
                full_title = title_element.get_text(strip=True)
                
                if ' - ' in full_title:
                    title_parts = full_title.rsplit(' - ', 1)
                    title = title_parts[0]
                    source = title_parts[1]
                else:
                    title = full_title
                    source_element = item.find('source')
                    source = source_element.get_text(strip=True) if source_element else "Bilinmiyor"
                
                # URL ve açıklama işleme
                description_element = item.find('description')
                description_text = description_element.get_text(strip=True) if description_element else ""
                description_html = BeautifulSoup(description_text, 'html.parser')
                link_tag = description_html.find('a')
                
                link_element = item.find('link')
                if link_tag and link_tag.get('href'):
                    url = link_tag['href']
                elif link_element:
                    url = link_element.get_text(strip=True)
                else:
                    url = ""
                
                # Yayın tarihi
                pub_date_element = item.find('pubdate')
                published_date = pub_date_element.get_text(strip=True) if pub_date_element else None
                
                # Son 1 saat kontrolü - sadece son 1 saatteki haberleri al
                if not is_within_last_hour(published_date):
                    continue
                
                article_data = {
                    'rank': index + 1,
                    'title': title,
                    'url': url,
                    'short_description': link_tag.get_text(strip=True) if link_tag else "",
                    'source': source,
                    'published_date': published_date
                }
                
                scraped_articles.append(article_data)
                
            except Exception as item_error:
                logger.warning(f"Haber işlenirken hata - {category_name}: {item_error}")
                continue
                
        logger.info(f"{category_name}: {len(scraped_articles)} haber çekildi (son 1 saat)")
        return scraped_articles
        
    except Exception as e:
        logger.error(f"Kategori hatası - {category_name}: {e}")
        return []


def save_to_file(data, filename):
    """Verileri JSON dosyasına kaydeder."""
    try:
        filepath = os.path.join(OUTPUT_FOLDER, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"Dosya kaydedildi: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Dosya kaydetme hatası: {e}")
        return False


def main():
    """Ana fonksiyon"""
    logger.info("Haber çekme işlemi başlatıldı")
    print("=" * 50)
    print("Google News Scraper - Lokal Versiyon")
    print("Son 1 saatteki haberleri çekiliyor...")
    print("=" * 50)
    
    # Ana veri yapısı
    all_scraped_data = {
        "scrape_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scrape_timestamp_local": datetime.now().isoformat(),
        "categories": {}
    }
    
    successful_categories = 0
    total_news_count = 0
    
    # Tüm kategorileri işle
    for category_name, rss_url in NEWS_CATEGORIES.items():
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        
        if articles:
            successful_categories += 1
            total_news_count += len(articles)
            
    print(f"\nÖZET:")
    print(f"✓ İşlenen kategori: {successful_categories}/{len(NEWS_CATEGORIES)}")
    print(f"✓ Toplam haber sayısı: {total_news_count}")
    
    # Dosyaya kaydet
    if successful_categories > 0:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"google_news_{timestamp}.json"
        
        if save_to_file(all_scraped_data, filename):
            print(f"✓ Veriler kaydedildi: {OUTPUT_FOLDER}/{filename}")
            return True
        else:
            print("✗ Dosya kaydetme başarısız")
            return False
    else:
        print("✗ Hiçbir kategori çekilemedi")
        return False


if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n✓ İşlem tamamlandı!")
        else:
            print("\n✗ İşlem başarısız!")
    
    except Exception as e:
        print(f"\n✗ Beklenmeyen hata: {e}")
        logger.error(f"Ana hata: {e}")
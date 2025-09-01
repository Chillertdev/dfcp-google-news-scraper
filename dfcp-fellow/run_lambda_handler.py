import json
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime, timezone, timedelta
import logging
import os
import warnings
from dateutil import parser as date_parser
import re

# BeautifulSoup XML uyarılarını gizle
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Logging konfigürasyonu
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Google News RSS URL'leri - Türkiye için 6 kategori
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}


def parse_google_news_date(published_date_str):
    """
    Google News RSS tarihlerini parse eder. Farklı formatları destekler.
    
    Args:
        published_date_str: RSS'den gelen tarih string'i
    
    Returns:
        datetime: UTC timezone'unda datetime objesi veya None
    """
    if not published_date_str:
        return None
        
    try:
        # Önce dateutil parser ile dene (çoğu formatı otomatik tanır)
        parsed_date = date_parser.parse(published_date_str)
        
        # Timezone bilgisi yoksa UTC olarak varsay
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        else:
            # Mevcut timezone'dan UTC'ye çevir
            parsed_date = parsed_date.astimezone(timezone.utc)
            
        return parsed_date
        
    except Exception as e:
        logger.warning(f"Tarih parse hatası ({published_date_str}): {e}")
        
        # Manuel parse dene - Google News bazen farklı formatlar kullanır
        try:
            # "5 saat önce" gibi relative time ifadeleri
            if "saat önce" in published_date_str.lower():
                hours = int(re.search(r'(\d+)\s*saat önce', published_date_str.lower()).group(1))
                return datetime.now(timezone.utc) - timedelta(hours=hours)
            elif "dakika önce" in published_date_str.lower():
                minutes = int(re.search(r'(\d+)\s*dakika önce', published_date_str.lower()).group(1))
                return datetime.now(timezone.utc) - timedelta(minutes=minutes)
            elif "gün önce" in published_date_str.lower():
                days = int(re.search(r'(\d+)\s*gün önce', published_date_str.lower()).group(1))
                return datetime.now(timezone.utc) - timedelta(days=days)
                
        except Exception as inner_e:
            logger.warning(f"Manuel tarih parse de başarısız ({published_date_str}): {inner_e}")
            
        return None


def is_within_last_hour(published_date_str):
    """
    Haberin yayınlanma tarihinin son 1 saat içinde olup olmadığını kontrol eder.
    
    Args:
        published_date_str: RSS'den gelen tarih string'i
    
    Returns:
        bool: Son 1 saat içindeyse True, değilse False
    """
    if not published_date_str:
        logger.warning("Yayın tarihi boş")
        return False
        
    pub_date = parse_google_news_date(published_date_str)
    if pub_date is None:
        return False
    
    # Şu anki zamanı UTC olarak al
    now_utc = datetime.now(timezone.utc)
    
    # İki zaman arasındaki farkı saniye olarak hesapla
    time_diff_seconds = (now_utc - pub_date).total_seconds()
    time_diff_hours = time_diff_seconds / 3600
    
    
    # Sadece son 1 saat içindeki haberler
    # Negatif değerler gelecekteki haberleri temsil eder (tolerans için -0.1 saat = 6 dakika)
    is_recent = -0.1 <= time_diff_hours <= 1.0
    
    if is_recent:
        logger.info(f"✓ SON 1 SAAT İÇİNDE: {published_date_str}")
    else:
        logger.info(f"✗ ESKİ HABER ({time_diff_hours:.1f}h): {published_date_str}")
        
    return is_recent


def extract_article_data(item):
    """
    RSS item'ından haber verilerini çıkarır.
    Google News RSS yapısını daha iyi handle eder.
    """
    try:
        # Haber başlığını çıkar
        title_element = item.find('title')
        if not title_element:
            logger.warning("Başlık elementi bulunamadı")
            return None
            
        full_title = title_element.get_text(strip=True)
        
        # Başlık formatı genellikle "Haber Başlığı - Kaynak Adı" şeklindedir
        if ' - ' in full_title:
            title_parts = full_title.rsplit(' - ', 1)  # Son - işaretinden böl
            title = title_parts[0].strip()
            source = title_parts[1].strip()
        else:
            title = full_title
            source = "Bilinmiyor"
        
        # Yayınlanma tarihini çıkar - farklı tag'leri dene
        published_date = None
        for date_tag in ['pubdate', 'pubDate', 'published']:
            date_element = item.find(date_tag)
            if date_element:
                published_date = date_element.get_text(strip=True)
                break
        
        # Haber URL'ini ve açıklamasını çıkar
        link_element = item.find('link')
        url = link_element.get_text(strip=True) if link_element else ""
        
        # Açıklama
        description_element = item.find('description')
        if description_element:
            description_text = description_element.get_text(strip=True)
            # HTML içindeki metin varsa onu da parse et
            description_html = BeautifulSoup(description_text, 'html.parser')
            short_description = description_html.get_text(strip=True)
        else:
            short_description = ""
        
        # GUID veya başka alternatif URL kaynakları
        if not url:
            guid_element = item.find('guid')
            if guid_element:
                url = guid_element.get_text(strip=True)
        
        article_data = {
            'title': title,
            'url': url,
            'short_description': short_description[:200] + ('...' if len(short_description) > 200 else ''),  # Kısalt
            'source': source,
            'published_date': published_date
        }
        
        logger.debug(f"Çıkarılan veri: {article_data}")
        return article_data
        
    except Exception as e:
        logger.warning(f"Haber verisi çıkarılırken hata: {e}")
        return None


def scrape_category(category_name, rss_url):
    """
    Belirli bir haber kategorisinden tüm haberleri çeker ve son 1 saatteki haberleri filtreler.
    
    Args:
        category_name: Kategori adı
        rss_url: RSS feed URL'i
    """
    
    try:
        # HTTP request için gerekli header'lar
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
        
        logger.info(f"=== {category_name.upper()} KATEGORİSİ ÇEKİLİYOR ===")
        logger.info(f"URL: {rss_url}")
        
        # Google News RSS'ine HTTP request gönder
        response = requests.get(rss_url, headers=headers, timeout=20)
        response.raise_for_status()
        
        logger.info(f"RSS response alındı - Status: {response.status_code}, Boyut: {len(response.content)} bytes")
        logger.info(f"Content-Type: {response.headers.get('Content-Type', 'Bilinmiyor')}")
        
        # XML içeriğini parse et - xml.parser tercih edilir ama html.parser da çalışır
        try:
            soup = BeautifulSoup(response.content, 'xml')  # xml parser dene
        except:
            soup = BeautifulSoup(response.content, 'html.parser')  # fallback
        
        # RSS feed başlık bilgisini logla
        channel_title = soup.find('title')
        if channel_title:
            logger.info(f"RSS Feed: {channel_title.get_text(strip=True)}")
        
        # Tüm haber itemlarını al
        all_items = soup.find_all('item')
        logger.info(f"Toplam {len(all_items)} haber item'ı bulundu")
        
        if len(all_items) == 0:
            logger.warning("Hiç haber item'ı bulunamadı! RSS yapısını kontrol edin.")
            # İlk birkaç tag'i logla debug için
            
        
        # Haberleri işle
        filtered_articles = []
        all_articles = []
        
        for index, item in enumerate(all_items):
            logger.info(f"\n--- Haber {index + 1}/{len(all_items)} ---")
            
            article_data = extract_article_data(item)
            if not article_data:
                logger.warning(f"Haber {index + 1} verisi çıkarılamadı")
                continue
                
            all_articles.append(article_data)
            logger.info(f"Başlık: {article_data['title'][:60]}...")
            logger.info(f"Kaynak: {article_data['source']}")
            logger.info(f"Tarih: {article_data['published_date']}")
            
            # Son 1 saat filtresi uygula
            if is_within_last_hour(article_data['published_date']):
                article_data['rank'] = len(filtered_articles) + 1
                filtered_articles.append(article_data)
                logger.info(f"✅ KABUL EDİLDİ (Son 1 saat içinde)")
           
        
        logger.info(f"\n=== {category_name.upper()} SONUÇ ===")
        logger.info(f"Toplam: {len(all_articles)} haber")
        logger.info(f"Son 1 saat içinde: {len(filtered_articles)} haber")
        
        return filtered_articles
        
    except Exception as e:
        logger.error(f"Kategori çekme hatası - {category_name}: {e}")
        logger.error(f"Hata detayı: {type(e).__name__}")
        return []


def main():
    """
    Ana fonksiyon. Tüm kategorileri işleyip lokal dosyaya kaydeder.
    Sadece son 1 saatteki haberleri filtreler.
    """
    
    logger.info(f"========== GOOGLE NEWS SCRAPER BAŞLATILDI ==========")
    logger.info(f"Filtre: Son 1 saat içindeki haberler")
    
    # Şu anki zamanı logla
    now_utc = datetime.now(timezone.utc)
    logger.info(f"Şu anki UTC zamanı: {now_utc}")
    logger.info(f"1 saat önce: {now_utc - timedelta(hours=1)}")
    
    # Ana veri yapısı
    all_scraped_data = {
        "scrape_timestamp_utc": now_utc.isoformat(),
        "filter_criteria": "Son 1 saat içindeki haberler",
        "categories": {}
    }
    
    successful_categories = 0
    total_articles = 0
    
    # Her kategori için haberleri çek
    for category_name, rss_url in NEWS_CATEGORIES.items():
        logger.info(f"\n{'='*50}")
        
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        
        article_count = len(articles)
        total_articles += article_count
        
        if articles:
            successful_categories += 1
            logger.info(f"✅ {category_name}: {article_count} haber")
            # İlk birkaç haberin başlığını göster
            for i, article in enumerate(articles[:3]):
                logger.info(f"   {i+1}. {article['title'][:50]}...")
        else:
            logger.warning(f"❌ {category_name}: 0 haber")
    
    # Genel özet
    logger.info(f"\n{'='*50}")
    logger.info(f"GENEL ÖZET:")
    logger.info(f"- Başarılı kategoriler: {successful_categories}/{len(NEWS_CATEGORIES)}")
    logger.info(f"- Toplam haber: {total_articles}")
    logger.info(f"- Filtre: Son 1 saat")
    
    # Veriyi dosyaya kaydet
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"google_news_{timestamp}.json"
        
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(all_scraped_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ Dosyaya kaydedildi: {file_name}")
        
        # Sonuç
        if total_articles > 0:
            result = {
                'statusCode': 200,
                'body': {
                    'message': f'{total_articles} haber kaydedildi',
                    'successful_categories': successful_categories,
                    'total_categories': len(NEWS_CATEGORIES),
                    'file': file_name
                }
            }
        else:
            result = {
                'statusCode': 200,
                'body': {
                    'message': 'Son 1 saatte haber bulunamadı',
                    'successful_categories': successful_categories,
                    'total_categories': len(NEWS_CATEGORIES),
                    'file': file_name
                }
            }
        
        logger.info(f"✅ İşlem tamamlandı: {json.dumps(result['body'], indent=2, ensure_ascii=False)}")
        return result
            
    except Exception as e:
        logger.error(f"❌ Dosya kaydetme hatası: {e}")
        return {
            'statusCode': 500,
            'body': {'error': 'Dosya kaydetme hatası', 'details': str(e)}
        }


if __name__ == "__main__":
    # Sadece son 1 saat içindeki haberleri kaydet
    result = main()
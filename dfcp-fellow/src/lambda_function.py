import json
import boto3
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
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS S3 konfigürasyonu
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'dfcp-scraped-bucket')
s3_client = boto3.client('s3')

# Google News RSS URL'leri - Türkiye için 6 kategori
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}


def is_within_last_hour(published_date_str):
    """
    Haberin yayınlanma tarihinin son 1 saat içinde olup olmadığını kontrol eder.
    Google News RSS tarih formatını doğru şekilde parse eder.
    
    Args:
        published_date_str: RSS'den gelen tarih string'i (örn: "Fri, 29 Aug 2025 03:51:00 GMT")
    
    Returns:
        bool: Son 1 saat içindeyse True, değilse False
    """
    if not published_date_str:
        logger.warning("Yayın tarihi boş")
        return False
        
    try:
        # RSS tarih formatını Python datetime objesine dönüştür
        # Google News genellikle "Fri, 29 Aug 2025 03:51:00 GMT" formatı kullanır
        pub_date = date_parser.parse(published_date_str)
        
        # Eğer timezone bilgisi yoksa UTC olarak varsay
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        else:
            # Timezone'u UTC'ye çevir
            pub_date = pub_date.astimezone(timezone.utc)
        
        # Şu anki zamanı UTC olarak al
        now_utc = datetime.now(timezone.utc)
        
        # İki zaman arasındaki farkı saniye olarak hesapla
        time_diff = (now_utc - pub_date).total_seconds()
        
        
        # TEST: 6 saat aralığı ile test (normal: 3600 saniye = 1 saat)
        # Negatif değerler gelecekteki haberleri temsil eder (saat farkı vb.)
        return -300 <= time_diff <= 3600  # 5 dakika gelecek toleransı + 6 saat geçmiş
        
    except Exception as e:
        logger.warning(f"Tarih parse hatası ({published_date_str}): {e}")
        return False


def extract_article_data(item):
    """
    RSS item'ından haber verilerini çıkarır.
    """
    try:
        # Haber başlığını al
        title_element = item.find('title')
        if not title_element:
            return None
            
        full_title = title_element.get_text(strip=True)
        
        # Başlık formatı genellikle "Haber Başlığı - Kaynak Adı" şeklindedir
        if ' - ' in full_title:
            title_parts = full_title.rsplit(' - ', 1)  # Son - işaretinden böl
            title = title_parts[0].strip()
            source = title_parts[1].strip()
        else:
            # Eğer - yoksa tüm başlık title olur, source'u ayrı etiket olarak ara
            title = full_title
            source_element = item.find('source')
            source = source_element.get_text(strip=True) if source_element else "Bilinmiyor"
        
        # Yayınlanma tarihini çıkar
        pub_date_element = item.find('pubdate')
        published_date = pub_date_element.get_text(strip=True) if pub_date_element else None
        
        # Haber URL'ini ve açıklamasını çıkar
        description_element = item.find('description')
        description_text = description_element.get_text(strip=True) if description_element else ""
        
        # Description içinde HTML var, onu da parse et
        description_html = BeautifulSoup(description_text, 'html.parser')
        link_tag = description_html.find('a')  # İlk link'i bul
        
        # URL'i önce description'daki link'ten, sonra link elementinden almaya çalış
        link_element = item.find('link')
        if link_tag and link_tag.get('href'):
            url = link_tag['href']
        elif link_element:
            url = link_element.get_text(strip=True)
        else:
            url = ""
        
        # Kısa açıklama metni
        short_description = link_tag.get_text(strip=True) if link_tag else ""
        
        return {
            'title': title,
            'url': url,
            'short_description': short_description,
            'source': source,
            'published_date': published_date
        }
        
    except Exception as e:
        logger.warning(f"Haber verisi çıkarılırken hata: {e}")
        return None


def scrape_category(category_name, rss_url):
    """
    Belirli bir haber kategorisinden tüm haberleri çeker ve son 1 saatteki haberleri filtreler.
    Google'ın orijinal haber sırasını korur.
    """
    
    try:
        # HTTP request için gerekli header'lar
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml',
            'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache'
        }
        
        logger.info(f"Kategori çekiliyor: {category_name}")
        
        # Google News RSS'ine HTTP request gönder
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        logger.info(f"{category_name} RSS response alındı, boyut: {len(response.content)} bytes")
        
        # İçeriği BeautifulSoup'daki html.parser ile parse et
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Tüm haber itemlarını al
        all_items = soup.find_all('item')
        logger.info(f"{category_name} toplam {len(all_items)} haber bulundu")
        
        # Son 1 saat içindeki haberleri topla
        filtered_articles = []
        all_articles = []  # Debug için tüm haberler
        
        for index, item in enumerate(all_items):
            article_data = extract_article_data(item)
            if not article_data:
                continue
                
            all_articles.append(article_data) # Debug için  
            
            # Son 1 saat kontrolü yap
            if is_within_last_hour(article_data['published_date']):
                article_data['rank'] = len(filtered_articles) + 1  # Rank ekle
                filtered_articles.append(article_data) #Son bir saatteki haberleri ekle
                logger.info(f"✓ {category_name} - Son 1 saatte: {article_data['title'][:50]}...")
           
        
        logger.info(f"{category_name}: {len(filtered_articles)}/{len(all_articles)} haber son 1 saat içinde")
        
        
        return filtered_articles
        
    except Exception as e:
        logger.error(f"Kategori hatası - {category_name}: {e}")
        return []  # Hata durumunda boş liste döndür


def lambda_handler(event, context):
    """
    AWS Lambda ana fonksiyonu. Tüm kategorileri işleyip S3'e kaydeder.
    """
    
    logger.info("Lambda başlatıldı")
    
    # Şu anki zamanı logla
    now_utc = datetime.now(timezone.utc)
    logger.info(f"Şu anki UTC zamanı: {now_utc}")
    logger.info(f"1 saat önce: {now_utc - timedelta(hours=1)}")
    
    # Tüm kategorilerin verilerini toplayacak ana veri yapısı
    all_scraped_data = {
        "scrape_timestamp_utc": now_utc.isoformat(),
        "filter_criteria": "Son 1 saat içindeki haberler",
        "categories": {}
    }
    
    successful_categories = 0
    total_articles = 0
    
    # Her kategori için haberleri çek
    for category_name, rss_url in NEWS_CATEGORIES.items():
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        
        article_count = len(articles)
        total_articles += article_count
        
        if articles:
            successful_categories += 1
            logger.info(f"✓ {category_name}: {article_count} haber")
        else:
            logger.warning(f"✗ {category_name}: 0 haber")
    
    # Özet logla
    logger.info(f"ÖZET: {successful_categories}/{len(NEWS_CATEGORIES)} kategori, toplam {total_articles} haber")
    
    
    try:
        # Dosya adı için timestamp oluştur
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"google_news_{timestamp}.json"
        
        # S3 bucket'ının var olup olmadığını kontrol et
        s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
        
        # Veriyi JSON formatına çevir (Türkçe karakterleri koru)
        json_data = json.dumps(all_scraped_data, indent=2, ensure_ascii=False)
        
        # S3'e yükle
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=file_name,
            Body=json_data,
            ContentType='application/json; charset=utf-8'
        )
        
        logger.info(f"S3'e kaydedildi: {file_name}")
        
        # Response
        if total_articles > 0:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'{total_articles} haber başarıyla kaydedildi',
                    'categories': successful_categories,
                    'file': file_name
                }, ensure_ascii=False)
            }
        else:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Son 1 saatte haber bulunamadı',
                    'categories_checked': len(NEWS_CATEGORIES),
                    'file': file_name
                }, ensure_ascii=False)
            }
            
    except Exception as e:
        logger.error(f"S3 hatası: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'S3 yükleme hatası',
                'details': str(e)
            })
        }
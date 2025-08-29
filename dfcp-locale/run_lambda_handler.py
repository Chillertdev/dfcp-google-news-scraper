# DFCP Google News Hourly Scraper - Lokal Versiyon

import json
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime, timezone
import logging
import os
import warnings
from dateutil import parser as date_parser

# BeautifulSoup XML uyarılarını gizle
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Logging konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Lokal dosya kaydetme için dizin
OUTPUT_DIR = "scraped_news"

# Google News RSS URL'leri - Türkiye için 6 kategori
NEWS_CATEGORIES = {
    "dunya": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "spor": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "is": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "teknoloji": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "eglence": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB?hl=tr&gl=TR&ceid=TR:tr",
    "saglik": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ?hl=tr&gl=TR&ceid=TR:tr"
}


def create_output_directory():
    """Çıktı dizinini oluştur"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        logger.info(f"Çıktı dizini oluşturuldu: {OUTPUT_DIR}")


def is_within_last_hour(published_date_str):
    """
    Haberin yayınlanma tarihinin son 1 saat içinde olup olmadığını kontrol eder.
    
    Args:
        published_date_str: RSS'den gelen tarih string'i
    
    Returns:
        bool: Son 1 saat içindeyse True, değilse False
    """
    if not published_date_str:
        return False
        
    try:
        # RSS tarih formatını Python datetime objesine dönüştür
        pub_date = date_parser.parse(published_date_str)
        
        # Eğer timezone bilgisi yoksa UTC olarak varsay
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        # Şu anki zamanı UTC olarak al
        now_utc = datetime.now(timezone.utc)
        
        # İki zaman arasındaki farkı saniye olarak hesapla
        time_diff = (now_utc - pub_date).total_seconds()
        
        # Son 1 saat içindeyse True döndür (0 ile 3600 saniye arası)
        return 0 <= time_diff <= 3600
        
    except Exception as e:
        logger.warning(f"Tarih parse hatası: {e}")
        return False


def scrape_category(category_name, rss_url):
    """
    Belirli bir haber kategorisinden tüm haberleri çeker ve son 1 saatteki haberleri filtreler.
    Google'ın orijinal haber sırasını korur.
    
    Args:
        category_name: Kategori adı (örn: "dunya", "spor")
        rss_url: Google News RSS URL'i
    
    Returns:
        list: Son 1 saat içindeki haberlerin listesi
    """
    
    try:
        # HTTP request için gerekli header'lar
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        logger.info(f"Kategori çekiliyor: {category_name}")
        
        # Google News RSS'ine HTTP request gönder
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # XML içeriğini BeautifulSoup ile parse et
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Tüm haber itemlarını al (limit yok, tüm haberleri çek)
        items = soup.find_all('item')
        
        # Son 1 saat içindeki haberleri topla
        filtered_articles = []
        
        for index, item in enumerate(items):
            try:
                # Haber başlığını çıkar
                title_element = item.find('title')
                if not title_element:
                    continue  # Başlık yoksa bu haberi atla
                    
                full_title = title_element.get_text(strip=True)
                
                # Başlık formatı genellikle "Haber Başlığı - Kaynak Adı" şeklindedir
                if ' - ' in full_title:
                    title_parts = full_title.rsplit(' - ', 1)  # Son - işaretinden böl
                    title = title_parts[0]
                    source = title_parts[1]
                else:
                    # Eğer - yoksa tüm başlık title olur, source'u ayrı etiket olarak ara
                    title = full_title
                    source_element = item.find('source')
                    source = source_element.get_text(strip=True) if source_element else "Bilinmiyor"
                
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
                
                # Yayınlanma tarihini çıkar
                pub_date_element = item.find('pubdate')
                published_date = pub_date_element.get_text(strip=True) if pub_date_element else None
                
                # ÖNEMLİ: Önce son 1 saat kontrolü yap, sonra listeye ekle
                if is_within_last_hour(published_date):
                    article_data = {
                        'title': title,
                        'url': url,
                        'short_description': link_tag.get_text(strip=True) if link_tag else "",
                        'source': source,
                        'published_date': published_date
                    }
                    filtered_articles.append(article_data)
                
            except Exception as item_error:
                logger.warning(f"Haber işlenirken hata - {category_name}: {item_error}")
                continue  # Bu haberde hata varsa bir sonrakine geç
        
        # Son 1 saat içindeki haberlere Google'ın orijinal sırasına göre rank ver
        # filtered_articles zaten Google'ın RSS sırasına göre geldi
        final_articles = []
        for new_rank, article in enumerate(filtered_articles, 1):
            article['rank'] = new_rank  # 1'den başlayarak rank ekle
            final_articles.append(article)
                
        logger.info(f"{category_name}: {len(final_articles)} haber çekildi (son 1 saat, Google sırası korundu)")
        return final_articles
        
    except Exception as e:
        logger.error(f"Kategori hatası - {category_name}: {e}")
        return []  # Hata durumunda boş liste döndür


def save_to_json(data, filename):
    """
    Veriyi JSON dosyası olarak kaydet
    
    Args:
        data: Kaydedilecek veri
        filename: Dosya adı
    
    Returns:
        bool: Başarılıysa True
    """
    try:
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"Dosya kaydedildi: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Dosya kaydetme hatası: {e}")
        return False


def main():
    """
    Ana fonksiyon. Tüm kategorileri işleyip JSON dosyasına kaydeder.
    """
    logger.info("Google News Scraper başlatıldı")
    
    # Çıktı dizinini oluştur
    create_output_directory()
    
    # Tüm kategorilerin verilerini toplayacak ana veri yapısı
    all_scraped_data = {
        "scrape_timestamp_utc": datetime.utcnow().isoformat(),  # İşlem zamanı
        "categories": {}
    }
    
    successful_categories = 0  # Başarılı kategori sayacı
    
    # Her kategori için haberleri çek
    for category_name, rss_url in NEWS_CATEGORIES.items():
        articles = scrape_category(category_name, rss_url)
        all_scraped_data["categories"][category_name] = articles
        
        # Eğer bu kategoriden haber geldiyse başarılı sayacını artır
        if articles:
            successful_categories += 1
    
    logger.info(f"{successful_categories}/{len(NEWS_CATEGORIES)} kategori başarılı")
    
    # En az bir kategori başarılıysa dosyaya kaydet
    if successful_categories > 0:
        # Dosya adı için timestamp oluştur
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"google_news_{timestamp}.json"
        
        # JSON dosyasına kaydet
        if save_to_json(all_scraped_data, filename):
            logger.info("✅ Tüm veriler başarıyla kaydedildi!")
            
            # Özet bilgi yazdır
            total_articles = sum(len(articles) for articles in all_scraped_data["categories"].values())
            logger.info(f"📊 Toplam {total_articles} adet son 1 saat içindeki haber kaydedildi")
            
            # Kategori bazında özet
            for category, articles in all_scraped_data["categories"].items():
                if articles:
                    logger.info(f"  📰 {category.upper()}: {len(articles)} haber")
        else:
            logger.error("❌ Dosya kaydetme başarısız!")
            return False
    else:
        logger.warning("⚠️ Hiçbir kategori çekilemedi")
        return False
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n🎉 Scraping tamamlandı! Veriler 'scraped_news' klasörüne kaydedildi.")
        else:
            print("\n❌ Scraping başarısız!")
    except KeyboardInterrupt:
        logger.info("⏹️ Kullanıcı tarafından durduruldu")
    except Exception as e:
        logger.error(f"💥 Beklenmeyen hata: {e}")
        print(f"\n❌ Hata oluştu: {e}")
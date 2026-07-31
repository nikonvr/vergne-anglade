import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List
from src.core.models import Act, Person

logger = logging.getLogger("certus.crawler.gallica")

class GallicaAPIClient:
    """Client API pour l'interrogation de la presse historique Gallica / BnF via SRU."""
    
    BASE_URL = "https://gallica.bnf.fr/SRU"

    def search_press_articles(self, query: str = "VERGNE AND Anglards", max_records: int = 5) -> List[Act]:
        """Interroge l'API SRU de Gallica et extrait les articles sous forme d'actes/événements de presse."""
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "query": f'text adj "{query}"',
            "maximumRecords": str(max_records)
        }
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        logger.info(f"Interrogation API Gallica BnF : {url}")
        
        acts: List[Act] = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CertusGenealogy/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read()
                
            root = ET.fromstring(content)
            # Namespace SRU Gallica
            ns = {"srw": "http://www.loc.gov/zing/srw/", "dc": "http://purl.org/dc/elements/1.1/"}
            
            for record in root.findall(".//srw:record", ns):
                title = record.find(".//dc:title", ns)
                identifier = record.find(".//dc:identifier", ns)
                date = record.find(".//dc:date", ns)
                
                title_str = title.text if title is not None else "Article de presse Gallica"
                link_str = identifier.text if identifier is not None else url
                date_str = date.text if date is not None else None

                act = Act(
                    act_type="Presse",
                    date=date_str,
                    location="Gallica / BnF",
                    confidence_score=0.85,
                    source_text=f"Gallica BnF : {title_str}",
                    source_type="API_GALLICA",
                    url_source=link_str,
                    reliability_score=0.80,
                    persons=[Person(first_name="Mentionné", last_name="VERGNE", role="article")]
                )
                acts.append(act)
        except Exception as e:
            logger.warning(f"Échec de l'interrogation Gallica API : {e}")

        return acts

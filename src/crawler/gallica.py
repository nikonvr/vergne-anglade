import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from src.core.models import Act

logger = logging.getLogger("certus.crawler.gallica")

# Valeurs par défaut, surchargeables à la construction du client.
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RECORDS = 5


class GallicaAPIClient:
    """
    Client API pour l'interrogation de la presse historique Gallica / BnF via SRU.

    Source RÉELLE : aucune donnée n'est fabriquée. Les actes retournés ne portent
    que les informations effectivement présentes dans la notice (titre, date,
    identifiant). Aucune personne n'est déduite d'une notice de presse : le
    rattachement d'un article à un individu relève d'une analyse ultérieure.
    """

    BASE_URL = "https://gallica.bnf.fr/SRU"
    NAMESPACES = {
        "srw": "http://www.loc.gov/zing/srw/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }

    def __init__(
        self,
        max_records: Optional[int] = None,
        timeout: Optional[float] = None,
        base_url: Optional[str] = None,
    ):
        self.max_records = int(max_records) if max_records else DEFAULT_MAX_RECORDS
        self.timeout = float(timeout) if timeout else DEFAULT_TIMEOUT
        self.base_url = base_url or self.BASE_URL

    def search_press_articles(self, query: str = "", max_records: Optional[int] = None) -> List[Act]:
        """
        Interroge l'API SRU de Gallica et extrait les notices sous forme d'actes de presse.

        Une requête vide n'interroge pas le service et retourne une liste vide :
        aucun critère de recherche implicite n'est ajouté.
        """
        search_expression = (query or "").strip()
        if not search_expression:
            logger.info("Interrogation Gallica ignorée : expression de recherche vide.")
            return []

        limit = int(max_records) if max_records else self.max_records
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "query": f'text adj "{search_expression}"',
            "maximumRecords": str(limit),
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        logger.info(f"Interrogation API Gallica BnF : {url}")

        content = self._fetch(url)
        if content is None:
            return []

        try:
            root = ET.fromstring(content)
        except ET.ParseError as parse_err:
            logger.error(
                f"Réponse Gallica illisible (XML invalide) pour la requête '{search_expression}' : {parse_err}"
            )
            return []

        acts: List[Act] = []
        for record in root.findall(".//srw:record", self.NAMESPACES):
            act = self._build_act(record, url)
            if act is not None:
                acts.append(act)

        logger.info(f"Gallica : {len(acts)} notice(s) exploitable(s) pour '{search_expression}'.")
        return acts

    def _fetch(self, url: str) -> Optional[bytes]:
        """Exécute l'appel HTTP. Retourne None en distinguant les causes d'échec réseau."""
        req = urllib.request.Request(url, headers={"User-Agent": "CertusGenealogy/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as http_err:
            logger.error(f"Gallica a répondu une erreur HTTP {http_err.code} ({http_err.reason}) : {url}")
        except urllib.error.URLError as url_err:
            logger.error(f"Échec réseau lors de l'appel à Gallica ({url_err.reason}) : {url}")
        except TimeoutError:
            logger.error(f"Délai dépassé ({self.timeout} s) lors de l'appel à Gallica : {url}")
        except OSError as os_err:
            logger.error(f"Échec système lors de l'appel à Gallica ({os_err}) : {url}")
        return None

    def _build_act(self, record: ET.Element, fallback_url: str) -> Optional[Act]:
        """Construit un acte de presse à partir des seuls champs Dublin Core réellement présents."""
        title_str = self._text(record, ".//dc:title")
        date_str = self._text(record, ".//dc:date")
        link_str = self._text(record, ".//dc:identifier") or fallback_url

        if not title_str:
            # Sans titre, la notice n'est pas exploitable : on ne fabrique pas de libellé.
            logger.debug("Notice Gallica ignorée : aucun titre Dublin Core exploitable.")
            return None

        return Act(
            act_type="Presse",
            date=date_str,
            location="Gallica / BnF",
            # La notice est réelle, mais aucun individu n'y est identifié :
            # la confiance porte uniquement sur l'existence de l'article.
            confidence_score=0.5,
            source_text=f"Gallica BnF : {title_str}",
            source_type="API_GALLICA",
            url_source=link_str,
            reliability_score=0.80,
            persons=[],
        )

    @staticmethod
    def _text(record: ET.Element, path: str) -> Optional[str]:
        """Retourne le texte nettoyé d'un sous-élément, ou None s'il est absent ou vide."""
        node = record.find(path, GallicaAPIClient.NAMESPACES)
        if node is None or node.text is None:
            return None
        value = node.text.strip()
        return value or None

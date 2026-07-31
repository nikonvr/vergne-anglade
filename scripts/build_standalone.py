"""Génère la page publique statique (index.html) depuis le fonds GEDCOM.

Politique de provenance : aucune donnée n'est inventée. Un acte sans transcription, sans
lien de registre ou sans score de confiance est affiché comme tel — la version précédente
comblait ces trous avec une URL d'archives, un texte « acte d'état civil original » et un
score de 0,95, ce qui présentait 334 actes comme sourcés alors qu'aucun ne l'était.
"""

import datetime
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")

from src.core.simulation import is_simulated_source_type  # noqa: E402
from src.database.engine import DatabaseManager  # noqa: E402
from src.database.models import DBAct, DBPerson  # noqa: E402
from src.database.repository import ActRepository  # noqa: E402
from src.export.gedcom import GedcomExporter  # noqa: E402
from src.genealogy.builder import TreeBuilder  # noqa: E402
from src.genealogy.variants import BRANCH_SURNAMES  # noqa: E402
from src.parser.gedcom_importer import GedcomImporter  # noqa: E402

logger = logging.getLogger("certus.build")

OUTPUT_FILE = Path("index.html")
DEFAULT_GEDCOM_PATH = "D:/drivefl/gene/2022/2026-02_export.ged"
GEDCOM_SOURCE_TYPE = "GEDCOM_HEREDIS"

# Versions de CDN épinglées : un import non versionné pouvait changer de comportement
# sans que la page ne soit modifiée.
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
PANZOOM_CDN = "https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"
TAILWIND_CDN = "https://cdn.tailwindcss.com"


def resolve_gedcom_path() -> Path:
    return Path(os.environ.get("CERTUS_GEDCOM_PATH") or DEFAULT_GEDCOM_PATH)


def _json_for_html(value) -> str:
    """Sérialise en JSON sûr à insérer dans une balise script."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def _short_place(place: str | None) -> str:
    """Ne conserve que la commune d'un lieu GEDCOM "Ville,CP,Département,...,PAYS,"."""
    if not place:
        return ""
    return place.split(",")[0].strip()


def sort_nodes_data(nodes: list[dict]) -> list[dict]:
    """Trie la liste d'individus par patronyme (majuscules) puis prénom (majuscules)."""
    return sorted(nodes, key=lambda n: ((n.get("last_name") or "").upper(), (n.get("first_name") or "").upper()))


def build_standalone_html() -> Path:
    """Régénère index.html. Lève FileNotFoundError si le fonds source est introuvable."""
    gedcom_path = resolve_gedcom_path()
    if not gedcom_path.exists():
        # On ne publie JAMAIS un arbre vide : l'ancienne version produisait dans ce cas une
        # page à 0 individu et 0 lien qui affichait pourtant « 246 membres & 349 liens ».
        raise FileNotFoundError(
            f"Fonds GEDCOM introuvable : {gedcom_path}. "
            "Définissez CERTUS_GEDCOM_PATH. La page publiée est laissée intacte."
        )

    build_time_str = datetime.datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
    db = DatabaseManager()
    db.init_db()

    acts = GedcomImporter(gedcom_path).parse_branch(list(BRANCH_SURNAMES))

    with db.get_session() as session:
        # Mod2 : on ne purge que les actes issus du GEDCOM. Les actes collectés par la
        # veille (Gallica, relevés CSV, OCR) étaient auparavant détruits à chaque build.
        obsolete = session.query(DBAct.id).filter(DBAct.source_type == GEDCOM_SOURCE_TYPE)
        obsolete_ids = [row[0] for row in obsolete.all()]
        if obsolete_ids:
            session.query(DBPerson).filter(DBPerson.act_id.in_(obsolete_ids)).delete(
                synchronize_session=False
            )
            session.query(DBAct).filter(DBAct.id.in_(obsolete_ids)).delete(
                synchronize_session=False
            )
            session.commit()
        ActRepository(session).save_acts(acts)

    with db.get_session() as session:
        stored_acts = ActRepository(session).get_all_acts()

    builder = TreeBuilder()
    tree = builder.process_acts(stored_acts)
    exporter = GedcomExporter()
    mermaid_code = exporter.export_mermaid(tree)
    gedcom_code = exporter.export_string(tree)

    report = builder.validate()
    if not report["is_acyclic"]:
        logger.error(
            "Arbre incohérent : %d cycle(s) de filiation. %s",
            len(report["cycles"]),
            report["cycles"],
        )

    # ---------------------------------------------------------------- données JS
    source_to_node = {p.source_id: nid for nid, p in tree.nodes.items() if p.source_id}

    def node_id_for(person) -> str | None:
        if person.source_id and person.source_id in source_to_node:
            return source_to_node[person.source_id]
        target = ((person.first_name or "").upper(), (person.last_name or "").upper())
        for nid, node in tree.nodes.items():
            if ((node.first_name or "").upper(), (node.last_name or "").upper()) == target:
                return nid
        return None

    # Mod8 : rattachement par identifiant stable. La modale retombait auparavant sur le
    # premier acte de la base quand aucun acte ne correspondait, et comparait les noms par
    # sous-chaîne (« Jean » correspondait à « Jeanne »).
    node_acts: dict[str, list[int]] = {}
    acts_data = []
    for act in stored_acts:
        simulated = act.is_simulated or is_simulated_source_type(act.source_type)
        acts_data.append(
            {
                "id": act.id,
                "act_type": act.act_type,
                "date": act.date,
                "location": act.location,
                "short_location": _short_place(act.location),
                "confidence": round(act.confidence_score * 100) if act.confidence_score else None,
                "source_text": act.source_text,
                "source_type": act.source_type,
                "url_source": act.url_source,
                "is_simulated": simulated,
                "persons": [
                    {
                        "first_name": p.first_name or "",
                        "last_name": p.last_name or "",
                        "role": p.role or "mentionné",
                        "occupation": p.occupation or "",
                    }
                    for p in act.persons
                ],
            }
        )
        for person in act.persons:
            nid = node_id_for(person)
            if nid is not None and act.id is not None:
                node_acts.setdefault(nid, [])
                if act.id not in node_acts[nid]:
                    node_acts[nid].append(act.id)

    nodes_data = [
        {
            "id": nid,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "mentions": p.mentions,
            "occupation": p.occupation,
            "birth_date": p.birth_date,
            "death_date": p.death_date,
            "place": _short_place(p.birth_place or p.death_place),
        }
        for nid, p in tree.nodes.items()
    ]
    # Tri par ordre alphabétique : Patronyme puis Prénom (ex: ANGLADE, puis VERGNE...)
    nodes_data = sort_nodes_data(nodes_data)

    # Liens de filiation, nécessaires côté client pour le zoom sur une branche (le sous-arbre
    # se calcule en JavaScript : cette page statique n'a pas de serveur à interroger).
    edges_data = [
        {"source_id": rel.source_id, "target_id": rel.target_id, "rel_type": rel.rel_type}
        for rel in tree.edges
    ]

    # ------------------------------------------------------- métriques calculées
    # Mod7 : plus aucun chiffre ni affirmation en dur dans la page.
    node_count = len(nodes_data)
    edge_count = len(tree.edges)
    act_count = len(acts_data)
    simulated_count = sum(1 for a in acts_data if a["is_simulated"])
    sourced = [a for a in acts_data if not a["is_simulated"] and a["confidence"] is not None]
    avg_confidence = round(sum(a["confidence"] for a in sourced) / len(sourced)) if sourced else None
    confidence_label = f"{avg_confidence} %" if avg_confidence is not None else "non évaluée"
    documented = sum(1 for a in acts_data if a["source_text"])
    places = Counter(a["short_location"] for a in acts_data if a["short_location"])
    main_place, main_place_count = places.most_common(1)[0] if places else ("Non précisée", 0)
    dated_nodes = sum(1 for n in nodes_data if n["birth_date"] or n["death_date"])
    surnames_label = " / ".join(BRANCH_SURNAMES)

    html_content = f"""<!DOCTYPE html>
<html lang="fr" class="antialiased text-slate-800 bg-slate-50">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>CERTUS Genealogy - Branche {surnames_label}</title>
    <script src="{TAILWIND_CDN}"></script>
    <script src="{MERMAID_CDN}"></script>
    <script src="{PANZOOM_CDN}"></script>
    <script>
        mermaid.initialize({{ startOnLoad: false, theme: 'neutral' }});
        tailwind.config = {{
            theme: {{
                extend: {{
                    colors: {{
                        brand: {{ 50: '#f0f9ff', 100: '#e0f2fe', 500: '#0ea5e9', 600: '#0284c7', 900: '#0c4a6e' }}
                    }}
                }}
            }}
        }};

        let panZoomTree = null;
        window.addEventListener('DOMContentLoaded', () => {{
            mermaid.run({{
                querySelector: '.mermaid',
                postRenderCallback: function(id) {{
                    const svg = document.querySelector('#' + id);
                    if (svg) {{
                        svg.style.maxWidth = 'none';
                        svg.style.width = '100%';
                        svg.style.height = '600px';
                        panZoomTree = svgPanZoom(svg, {{
                            zoomEnabled: true,
                            controlIconsEnabled: false,
                            mouseWheelZoomEnabled: true,
                            preventMouseEventsDefault: true,
                            fit: true,
                            center: true,
                            minZoom: 0.05,
                            maxZoom: 10,
                            zoomScaleSensitivity: 0.2
                        }});
                    }}
                }}
            }});
        }});

        function zoomInTree() {{ if (panZoomTree) panZoomTree.zoomIn(); }}
        function zoomOutTree() {{ if (panZoomTree) panZoomTree.zoomOut(); }}
        function resetTree() {{ if (panZoomTree) {{ panZoomTree.reset(); panZoomTree.fit(); panZoomTree.center(); }} }}
    </script>
    <style>
        .fade-in {{ animation: fadeIn 0.4s ease-in-out; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        @keyframes marquee {{
            0% {{ transform: translateX(0%); }}
            100% {{ transform: translateX(-100%); }}
        }}
        .animate-marquee {{
            display: inline-block;
            white-space: nowrap;
            animation: marquee 60s linear infinite;
        }}
        .animate-marquee:hover {{ animation-play-state: paused; }}
        .mermaid {{ width: 100%; overflow: auto; }}
        .mermaid svg {{
            max-width: none !important;
            min-width: 1800px !important;
            min-height: 500px !important;
            height: auto !important;
        }}
        html {{ scroll-behavior: smooth; }}
    </style>
</head>
<body class="min-h-screen flex flex-col font-sans">
    <header class="bg-brand-900 text-white py-6 px-8 shadow-md">
        <div class="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
                <h1 class="text-2xl font-bold flex flex-wrap items-center gap-2">
                    <span>🏛️ CERTUS GENEALOGY</span>
                    <span class="text-xs bg-brand-600 text-white px-2.5 py-0.5 rounded-full uppercase tracking-wider font-semibold">Page publique</span>
                    <span class="text-[10px] bg-emerald-700 text-emerald-100 px-2 py-0.5 rounded-full font-mono">MàJ : {build_time_str}</span>
                </h1>
                <p class="text-sm text-brand-100 mt-1">Branche patronymique <strong>{surnames_label}</strong></p>
            </div>
            <div class="flex items-center gap-3">
                <button id="btn-gedcom" class="bg-white text-brand-900 hover:bg-brand-50 px-4 py-2 rounded-lg text-xs font-bold transition shadow">
                    📥 Exporter GEDCOM (.ged)
                </button>
            </div>
        </div>
    </header>

    <div class="bg-brand-900 text-white border-t border-brand-800 py-2.5 px-4 shadow-inner text-xs overflow-hidden">
        <div class="max-w-7xl mx-auto flex items-center gap-3">
            <span class="bg-brand-500 text-white font-extrabold px-2.5 py-0.5 rounded text-[10px] uppercase tracking-wider shrink-0 shadow-sm">📢 GUIDE VISITEUR</span>
            <div class="overflow-hidden relative w-full flex items-center">
                <div class="animate-marquee cursor-pointer font-medium text-brand-100" title="Passez votre souris pour mettre en pause">
                    📖 <b>BIENVENUE SUR CETTE GÉNÉALOGIE !</b> &nbsp;&bull;&nbsp;
                    🌳 <b>1. L'ARBRE VISUEL :</b> chaque rectangle représente un membre, les flèches montrent la filiation (Parent &rarr; Enfant) &nbsp;&bull;&nbsp;
                    📋 <b>2. LE TABLEAU :</b> retrouvez les membres, leurs métiers et leurs actes &nbsp;&bull;&nbsp;
                    📜 <b>3. LES ACTES :</b> cliquez sur « Voir les actes » pour afficher ce que la source contient réellement &nbsp;&bull;&nbsp;
                    🔍 <b>4. LA RECHERCHE :</b> tapez un prénom dans la case pour filtrer instantanément &nbsp;&bull;&nbsp;
                    📥 <b>5. EXPORTATION :</b> cliquez sur « Exporter GEDCOM » en haut à droite pour télécharger la sauvegarde ! (Survolez pour mettre en pause)
                </div>
            </div>
        </div>
    </div>

    <main class="max-w-7xl mx-auto w-full flex-1 p-6 md:p-8 space-y-8 fade-in">
        <div class="bg-gradient-to-r from-brand-900 to-brand-700 text-white rounded-xl p-6 shadow-md">
            <div class="flex items-start space-x-4">
                <div class="bg-white/10 p-3 rounded-lg text-3xl">📖</div>
                <div>
                    <h2 class="text-xl font-bold">Espace généalogique de la branche {surnames_label}</h2>
                    <p class="mt-1 text-sm text-brand-100 leading-relaxed">
                        Cette page présente {node_count} individus consolidés et {edge_count} liens de filiation,
                        reconstitués à partir de {act_count} actes du fonds familial.
                    </p>
                    <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">📜 1. Les actes</span>
                            {documented} acte(s) sur {act_count} disposent d'une transcription consultable.
                        </div>
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">🌳 2. L'arbre visuel</span>
                            Les cartes sont reliées par des flèches allant du parent vers l'enfant.
                        </div>
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">🔍 3. La recherche</span>
                            Filtrez instantanément par prénom, patronyme ou métier.
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-4 gap-5">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Individus consolidés</div>
                <div class="text-3xl font-extrabold text-brand-900 mt-1">{node_count}</div>
                <div class="text-[11px] text-slate-500 mt-1">{dated_nodes} avec date connue</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Liens de filiation</div>
                <div class="text-3xl font-extrabold text-brand-900 mt-1">{edge_count}</div>
                <div class="text-[11px] text-slate-500 mt-1">{act_count} actes exploités</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Localisation la plus fréquente</div>
                <div class="text-lg font-bold text-brand-600 mt-2">{main_place}</div>
                <div class="text-[11px] text-slate-500 mt-1">{main_place_count} acte(s)</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Confiance moyenne</div>
                <div class="text-2xl font-bold text-emerald-600 mt-1">{confidence_label}</div>
                <div class="text-[11px] text-slate-500 mt-1">{simulated_count} acte(s) non sourcé(s)</div>
            </div>
        </div>

        <div class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-4">
            <div class="flex flex-col lg:flex-row lg:items-center justify-between pb-4 border-b border-slate-100 gap-3">
                <div>
                    <h3 class="text-lg font-bold text-slate-900 flex flex-wrap items-center gap-2">
                        <span>🌳 Arbre généalogique visuel &amp; liens de filiation</span>
                        <span class="text-xs bg-emerald-100 text-emerald-800 font-bold px-2.5 py-0.5 rounded-full border border-emerald-300">🖐️ Glisser-déplacer &amp; zoom actifs</span>
                    </h3>
                    <p class="text-xs text-slate-500 mt-1">Molette pour zoomer, clic gauche maintenu pour vous déplacer ({node_count} membres &amp; {edge_count} liens)</p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                    <button onclick="zoomInTree()" class="bg-slate-100 hover:bg-brand-50 hover:text-brand-600 text-slate-700 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-bold transition shadow-sm">➕ Zoom +</button>
                    <button onclick="zoomOutTree()" class="bg-slate-100 hover:bg-brand-50 hover:text-brand-600 text-slate-700 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-bold transition shadow-sm">➖ Zoom -</button>
                    <button onclick="resetTree()" class="bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded-lg text-xs font-bold transition shadow-sm">🎯 Centrer / Réinitialiser</button>
                </div>
            </div>
            <div class="w-full bg-slate-50 border border-slate-200 rounded-xl overflow-hidden shadow-inner relative" style="height: 620px;">
                <div class="mermaid h-full w-full">
{mermaid_code}
                </div>
            </div>
        </div>

        <div class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-4">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4">
                <h3 class="text-lg font-bold text-slate-900">📋 Liste des individus <span id="row-count" class="text-sm font-normal text-slate-500"></span></h3>
                <input id="filter-input" type="text" placeholder="🔍 Chercher un prénom, un patronyme ou un métier..." class="px-4 py-2 border rounded-lg text-sm bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500 w-full sm:w-80">
            </div>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200 text-sm">
                    <thead id="table-head" class="bg-slate-50 text-slate-500 font-semibold uppercase text-xs">
                        <tr>
                            <th data-sort-key="name" class="px-4 py-3 text-left cursor-pointer hover:bg-slate-100 transition select-none">
                                <span class="inline-flex items-center gap-1">Prénom &amp; nom <span class="sort-icon text-slate-400">↕</span></span>
                            </th>
                            <th data-sort-key="dates" class="px-4 py-3 text-left cursor-pointer hover:bg-slate-100 transition select-none">
                                <span class="inline-flex items-center gap-1">Dates <span class="sort-icon text-slate-400">↕</span></span>
                            </th>
                            <th data-sort-key="place" class="px-4 py-3 text-left cursor-pointer hover:bg-slate-100 transition select-none">
                                <span class="inline-flex items-center gap-1">Lieu <span class="sort-icon text-slate-400">↕</span></span>
                            </th>
                            <th data-sort-key="occupation" class="px-4 py-3 text-left cursor-pointer hover:bg-slate-100 transition select-none">
                                <span class="inline-flex items-center gap-1">Profession <span class="sort-icon text-slate-400">↕</span></span>
                            </th>
                            <th data-sort-key="mentions" class="px-4 py-3 text-center cursor-pointer hover:bg-slate-100 transition select-none">
                                <span class="inline-flex items-center gap-1 justify-center">Mentions <span class="sort-icon text-slate-400">↕</span></span>
                            </th>
                            <th data-sort-key="acts" class="px-4 py-3 text-right cursor-pointer hover:bg-slate-100 transition select-none">
                                <span class="inline-flex items-center gap-1 justify-end">Actes <span class="sort-icon text-slate-400">↕</span></span>
                            </th>
                        </tr>
                    </thead>
                    <tbody id="table-body" class="divide-y divide-slate-100"></tbody>
                </table>
            </div>
        </div>
    </main>

    <div id="act-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center hidden z-50 p-4">
        <div class="bg-white rounded-2xl max-w-2xl w-full shadow-2xl overflow-hidden border border-slate-100 flex flex-col max-h-[90vh]">
            <div class="bg-brand-900 text-white px-6 py-4 flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="text-xl">📜</span>
                    <h3 id="modal-title" class="font-bold text-lg"></h3>
                </div>
                <button id="modal-close-top" class="text-brand-200 hover:text-white text-2xl font-bold px-2 py-0.5 rounded">&times;</button>
            </div>
            <div id="modal-body" class="p-6 overflow-y-auto space-y-5 text-sm"></div>
            <div class="bg-slate-50 px-6 py-3 border-t border-slate-100 text-right">
                <button id="modal-close-bottom" class="px-5 py-2 bg-slate-200 hover:bg-slate-300 text-slate-800 rounded-lg text-xs font-bold transition">Fermer</button>
            </div>
        </div>
    </div>

    <!-- Sous-arbre : zoom sur une branche (ascendants + descendants d'une personne) -->
    <div id="subtree-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center hidden z-50 p-4">
        <div class="bg-white rounded-2xl max-w-5xl w-full shadow-2xl overflow-hidden border border-slate-100 flex flex-col h-[92vh]">
            <div class="bg-brand-900 text-white px-6 py-4 flex items-center justify-between gap-3 flex-wrap shrink-0">
                <div class="flex items-center gap-2">
                    <span class="text-xl">🌳</span>
                    <h3 id="subtree-title" class="font-bold text-lg"></h3>
                </div>
                <div class="flex items-center gap-2 text-xs">
                    <label class="flex items-center gap-1 text-brand-100">Ascendants
                        <input id="subtree-up" type="number" min="0" max="15" value="2" class="w-14 px-1.5 py-1 rounded text-slate-900 text-center">
                    </label>
                    <label class="flex items-center gap-1 text-brand-100">Descendants
                        <input id="subtree-down" type="number" min="0" max="15" value="2" class="w-14 px-1.5 py-1 rounded text-slate-900 text-center">
                    </label>
                    <label class="flex items-center gap-1 text-brand-100 cursor-pointer select-none">
                        <input id="subtree-siblings" type="checkbox" checked class="rounded accent-brand-500"> Fratrie
                    </label>
                    <button id="subtree-recompute" class="bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded-lg font-bold transition">Recalculer</button>
                    <div class="flex items-center gap-1 bg-brand-800/80 p-1 rounded-lg text-xs ml-2 border border-brand-700">
                        <button id="subtree-zoom-in" title="Zoom avant" class="px-2 py-0.5 hover:bg-brand-700 rounded text-white font-bold transition">➕</button>
                        <button id="subtree-zoom-out" title="Zoom arrière" class="px-2 py-0.5 hover:bg-brand-700 rounded text-white font-bold transition">➖</button>
                        <button id="subtree-zoom-fit" title="Ajuster à l'écran" class="px-2 py-0.5 hover:bg-brand-700 rounded text-white font-bold transition">🎯</button>
                        <button id="subtree-zoom-reset" title="Réinitialiser" class="px-2 py-0.5 hover:bg-brand-700 rounded text-white font-bold transition">🔄</button>
                    </div>
                </div>
                <button id="subtree-close-top" class="text-brand-200 hover:text-white text-2xl font-bold px-2 py-0.5 rounded">&times;</button>
            </div>
            <p id="subtree-count" class="px-6 pt-3 text-xs text-slate-500 shrink-0"></p>
            <!-- min-h-0 est indispensable : sans lui, un enfant flex-1 refuse de descendre
                 sous la hauteur intrinsèque de son contenu (ici le SVG), ce qui annulerait
                 la hauteur fixe du conteneur ci-dessus et ferait déborder la modale. -->
            <div class="p-4 flex-1 min-h-0 overflow-hidden">
                <div id="subtree-container" class="w-full h-full bg-slate-50 border border-slate-200 rounded-xl overflow-hidden">
                    <div id="subtree-mermaid" class="w-full h-full"></div>
                </div>
            </div>
            <div class="bg-slate-50 px-6 py-3 border-t border-slate-100 text-right">
                <button id="subtree-close-bottom" class="px-5 py-2 bg-slate-200 hover:bg-slate-300 text-slate-800 rounded-lg text-xs font-bold transition">Fermer</button>
            </div>
        </div>
    </div>

    <!-- Fiche individuelle : détails, 2 parents, frères & sœurs, enfants -->
    <div id="profile-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center hidden z-50 p-4">
        <div class="bg-white rounded-2xl max-w-2xl w-full shadow-2xl overflow-hidden border border-slate-100 flex flex-col max-h-[90vh]">
            <div class="bg-brand-900 text-white px-6 py-4 flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="text-xl">📇</span>
                    <h3 id="profile-modal-title" class="font-bold text-lg">Fiche individuelle</h3>
                </div>
                <button id="profile-modal-close-top" class="text-brand-200 hover:text-white text-2xl font-bold px-2 py-0.5 rounded">&times;</button>
            </div>
            <div id="profile-modal-body" class="p-6 overflow-y-auto space-y-5 text-sm"></div>
            <div class="bg-slate-50 px-6 py-3 border-t border-slate-100 text-right">
                <button id="profile-modal-close-bottom" class="px-5 py-2 bg-slate-200 hover:bg-slate-300 text-slate-800 rounded-lg text-xs font-bold transition">Fermer</button>
            </div>
        </div>
    </div>

    <footer class="bg-slate-900 text-slate-400 py-6 text-center text-xs border-t border-slate-800 mt-12">
        CERTUS GENEALOGY — page publique générée le {build_time_str}
    </footer>

    <script>
        const NODES = {_json_for_html(nodes_data)};
        const ACTS = {_json_for_html(acts_data)};
        const NODE_ACTS = {_json_for_html(node_acts)};
        const EDGES = {_json_for_html(edges_data)};
        const RAW_GEDCOM = {_json_for_html(gedcom_code)};

        const ACTS_BY_ID = new Map(ACTS.map(a => [a.id, a]));
        const NODES_BY_ID = new Map(NODES.map(n => [n.id, n]));

        // Toutes les valeurs issues des données sont posées via textContent ou setAttribute :
        // aucun nom n'est interpolé dans du HTML ni dans un attribut d'événement, si bien
        // qu'une apostrophe ou un chevron dans un patronyme ne peut plus rien casser.
        function cell(row, text, className) {{
            const td = document.createElement('td');
            td.className = className;
            td.textContent = text || '';
            row.appendChild(td);
            return td;
        }}

        function renderTable(data) {{
            const tbody = document.getElementById('table-body');
            tbody.replaceChildren();
            data.forEach(item => {{
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-50 transition';
                cell(tr, ((item.first_name || '') + ' ' + (item.last_name || '')).trim(), 'px-4 py-3 font-bold text-slate-900');
                const dates = [item.birth_date, item.death_date].filter(Boolean).join(' – ');
                cell(tr, dates || '—', 'px-4 py-3 text-slate-600 whitespace-nowrap');
                cell(tr, item.place || '—', 'px-4 py-3 text-slate-600');
                cell(tr, item.occupation || '—', 'px-4 py-3 text-slate-600');

                const mentions = document.createElement('td');
                mentions.className = 'px-4 py-3 text-center';
                const badge = document.createElement('span');
                badge.className = 'bg-brand-100 text-brand-800 text-xs px-2.5 py-1 rounded-full font-semibold';
                badge.textContent = item.mentions + ' acte(s)';
                mentions.appendChild(badge);
                tr.appendChild(mentions);

                const actionCell = document.createElement('td');
                actionCell.className = 'px-4 py-3 text-right space-x-1.5 whitespace-nowrap';
                const count = (NODE_ACTS[item.id] || []).length;
                const button = document.createElement('button');
                button.className = count
                    ? 'inline-flex items-center gap-1 bg-brand-50 hover:bg-brand-100 text-brand-700 text-xs px-3 py-1.5 rounded-lg font-bold border border-brand-200 transition shadow-sm'
                    : 'inline-flex items-center gap-1 bg-slate-50 text-slate-400 text-xs px-3 py-1.5 rounded-lg font-bold border border-slate-200 cursor-not-allowed';
                button.textContent = count ? '📜 Voir les actes (' + count + ')' : 'Aucun acte';
                button.disabled = !count;
                button.setAttribute('data-node-id', item.id);
                button.setAttribute('data-role', 'acts');
                actionCell.appendChild(button);

                const branchButton = document.createElement('button');
                branchButton.className = 'inline-flex items-center gap-1 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs px-3 py-1.5 rounded-lg font-bold border border-emerald-200 transition shadow-sm';
                branchButton.textContent = '🌳 Voir la branche';
                branchButton.setAttribute('data-node-id', item.id);
                branchButton.setAttribute('data-role', 'subtree');
                actionCell.appendChild(branchButton);

                const profileButton = document.createElement('button');
                profileButton.className = 'inline-flex items-center gap-1 bg-sky-50 hover:bg-sky-100 text-sky-700 text-xs px-3 py-1.5 rounded-lg font-bold border border-sky-200 transition shadow-sm';
                profileButton.textContent = '📇 Fiche';
                profileButton.setAttribute('data-node-id', item.id);
                profileButton.setAttribute('data-role', 'profile');
                actionCell.appendChild(profileButton);

                tr.appendChild(actionCell);
                tbody.appendChild(tr);
            }});
            document.getElementById('row-count').textContent = '(' + data.length + ')';
        }}

        function metaBlock(label, value) {{
            const wrapper = document.createElement('div');
            const title = document.createElement('span');
            title.className = 'text-slate-500 block uppercase font-semibold';
            title.textContent = label;
            const content = document.createElement('span');
            content.className = 'font-bold text-slate-800';
            content.textContent = value;
            wrapper.append(title, content);
            return wrapper;
        }}

        function renderAct(act) {{
            const card = document.createElement('div');
            card.className = 'border border-slate-200 rounded-xl p-4 space-y-3';

            if (act.is_simulated) {{
                const flag = document.createElement('div');
                flag.className = 'bg-amber-100 border border-amber-300 text-amber-900 text-xs font-bold px-3 py-2 rounded-lg';
                flag.textContent = '⚠️ Donnée non sourcée (simulation) — à ne pas considérer comme une preuve.';
                card.appendChild(flag);
            }}

            const meta = document.createElement('div');
            meta.className = 'grid grid-cols-2 sm:grid-cols-3 gap-3 bg-slate-50 p-3.5 rounded-xl border border-slate-200/80 text-xs';
            meta.appendChild(metaBlock("Type d'acte", act.act_type || 'Non précisé'));
            const dateLoc = [act.date, act.short_location].filter(Boolean).join(' — ');
            meta.appendChild(metaBlock('Date et lieu', dateLoc || 'Non précisés'));
            meta.appendChild(metaBlock('Confiance', act.confidence === null ? 'non évaluée' : act.confidence + ' %'));
            card.appendChild(meta);

            const transcriptTitle = document.createElement('h4');
            transcriptTitle.className = 'font-bold text-slate-800 text-xs uppercase tracking-wider';
            transcriptTitle.textContent = act.source_text ? 'Extrait enregistré pour cet acte' : 'Transcription';
            card.appendChild(transcriptTitle);

            const transcript = document.createElement('div');
            if (act.source_text) {{
                transcript.className = 'bg-amber-50/60 border-l-4 border-amber-500 p-4 rounded-r-xl font-serif text-slate-800 italic leading-relaxed';
                transcript.textContent = '« ' + act.source_text + ' »';
            }} else {{
                transcript.className = 'bg-slate-50 border-l-4 border-slate-300 p-4 rounded-r-xl text-slate-500 italic';
                transcript.textContent = "Aucune transcription n'est disponible pour cet acte.";
            }}
            card.appendChild(transcript);

            const footer = document.createElement('div');
            footer.className = 'flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100 text-xs';
            const provenance = document.createElement('div');
            provenance.className = 'flex items-center gap-2';
            const provLabel = document.createElement('span');
            provLabel.className = 'text-slate-500';
            provLabel.textContent = 'Provenance :';
            const provBadge = document.createElement('span');
            provBadge.className = 'bg-brand-100 text-brand-800 font-bold px-2.5 py-0.5 rounded-full';
            provBadge.textContent = act.source_type || 'inconnue';
            provenance.append(provLabel, provBadge);
            footer.appendChild(provenance);

            // Aucun lien n'est fabriqué : sans url_source, on l'indique explicitement.
            if (act.url_source) {{
                const link = document.createElement('a');
                link.className = 'inline-flex items-center gap-1 bg-brand-600 hover:bg-brand-700 text-white font-bold px-3 py-1.5 rounded-lg shadow-sm transition';
                link.href = act.url_source;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = "🔗 Registre d'origine →";
                footer.appendChild(link);
            }} else {{
                const none = document.createElement('span');
                none.className = 'text-slate-400 italic';
                none.textContent = 'Lien de registre non renseigné';
                footer.appendChild(none);
            }}
            card.appendChild(footer);

            if (act.persons && act.persons.length) {{
                const peopleTitle = document.createElement('h4');
                peopleTitle.className = 'font-bold text-slate-800 text-xs uppercase tracking-wider pt-2 border-t border-slate-100';
                peopleTitle.textContent = 'Personnes citées dans cet acte';
                card.appendChild(peopleTitle);
                act.persons.forEach(p => {{
                    const row = document.createElement('div');
                    row.className = 'flex items-center justify-between bg-slate-50 px-3 py-2 rounded-lg border border-slate-200/60 text-xs';
                    const name = document.createElement('span');
                    name.className = 'font-bold text-slate-800';
                    name.textContent = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
                    const role = document.createElement('span');
                    role.className = 'text-slate-500';
                    role.textContent = (p.occupation ? p.occupation + ' • ' : '') + (p.role || '');
                    row.append(name, role);
                    card.appendChild(row);
                }});
            }}
            return card;
        }}

        function openModalForNode(nodeId) {{
            const node = NODES_BY_ID.get(nodeId);
            if (!node) return;
            const ids = NODE_ACTS[nodeId] || [];
            document.getElementById('modal-title').textContent =
                'Actes de ' + ((node.first_name || '') + ' ' + (node.last_name || '')).trim();

            const body = document.getElementById('modal-body');
            body.replaceChildren();
            if (!ids.length) {{
                const empty = document.createElement('p');
                empty.className = 'text-slate-500 italic';
                empty.textContent = "Aucun acte n'est rattaché à cette personne dans le fonds.";
                body.appendChild(empty);
            }} else {{
                ids.forEach(id => {{
                    const act = ACTS_BY_ID.get(id);
                    if (act) body.appendChild(renderAct(act));
                }});
            }}
            document.getElementById('act-modal').classList.remove('hidden');
        }}

        function closeModal() {{ document.getElementById('act-modal').classList.add('hidden'); }}

        function closeProfileModal() {{
            document.getElementById('profile-modal').classList.add('hidden');
        }}

        function createPersonCard(person, subtitle) {{
            const card = document.createElement('div');
            card.className = 'flex items-center justify-between bg-slate-50 hover:bg-slate-100 p-3 rounded-xl border border-slate-200/80 transition cursor-pointer';
            
            const info = document.createElement('div');
            const name = document.createElement('div');
            name.className = 'font-bold text-slate-900';
            name.textContent = ((person.first_name || '') + ' ' + (person.last_name || '')).trim() || 'Inconnu';
            
            const dates = [person.birth_date, person.death_date].filter(Boolean).join(' – ');
            const details = [dates, person.place, person.occupation].filter(Boolean).join(' • ');
            
            const sub = document.createElement('div');
            sub.className = 'text-xs text-slate-500 mt-0.5';
            sub.textContent = (subtitle ? subtitle + ' — ' : '') + (details || "Aucune précision d'état civil");
            
            info.append(name, sub);
            
            const action = document.createElement('span');
            action.className = 'text-xs font-bold text-brand-600 hover:underline shrink-0 ml-3';
            action.textContent = 'Voir la fiche →';
            
            card.append(info, action);
            card.addEventListener('click', () => openProfileModal(person.id));
            return card;
        }}

        function openProfileModal(nodeId) {{
            const node = NODES_BY_ID.get(nodeId);
            if (!node) return;

            document.getElementById('profile-modal-title').textContent =
                'Fiche individuelle : ' + ((node.first_name || '') + ' ' + (node.last_name || '')).trim();

            const body = document.getElementById('profile-modal-body');
            body.replaceChildren();

            // 1. En-tête : Informations personnelles
            const mainCard = document.createElement('div');
            mainCard.className = 'bg-brand-50/50 border border-brand-200/80 rounded-xl p-4 space-y-3';
            
            const mainName = document.createElement('h4');
            mainName.className = 'text-base font-bold text-brand-950';
            mainName.textContent = ((node.first_name || '') + ' ' + (node.last_name || '')).trim();
            
            const grid = document.createElement('div');
            grid.className = 'grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs';
            
            const dates = [node.birth_date, node.death_date].filter(Boolean).join(' – ');
            grid.appendChild(metaBlock('Dates', dates || 'Non précisées'));
            grid.appendChild(metaBlock('Lieu', node.place || 'Non précisé'));
            grid.appendChild(metaBlock('Profession', node.occupation || 'Non précisée'));
            
            mainCard.append(mainName, grid);
            body.appendChild(mainCard);

            // 2. Parents (Père et Mère)
            const parentEdges = EDGES.filter(e => e.target_id === nodeId && FILIATION_REL_TYPES.has((e.rel_type || '').toLowerCase()));
            let fatherNode = null;
            let motherNode = null;

            parentEdges.forEach(e => {{
                const rt = (e.rel_type || '').toLowerCase();
                const p = NODES_BY_ID.get(e.source_id);
                if (!p) return;
                if (rt.startsWith('p') || rt === 'father' || rt === 'husb') {{
                    fatherNode = p;
                }} else if (rt.startsWith('m') || rt === 'mother' || rt === 'wife') {{
                    motherNode = p;
                }} else if (!fatherNode) {{
                    fatherNode = p;
                }} else if (!motherNode) {{
                    motherNode = p;
                }}
            }});

            const parentsSection = document.createElement('div');
            parentsSection.className = 'space-y-2';
            
            const parentsTitle = document.createElement('h5');
            parentsTitle.className = 'font-bold text-slate-800 text-xs uppercase tracking-wider flex items-center gap-1.5';
            parentsTitle.textContent = '👨‍👩‍👦 Parents';
            parentsSection.appendChild(parentsTitle);

            const parentsGrid = document.createElement('div');
            parentsGrid.className = 'space-y-2';

            if (fatherNode) {{
                parentsGrid.appendChild(createPersonCard(fatherNode, 'Père'));
            }} else {{
                const empty = document.createElement('div');
                empty.className = 'bg-slate-50 p-3 rounded-xl border border-slate-200/60 text-xs text-slate-400 italic';
                empty.textContent = 'Père : non identifié dans les actes du fonds';
                parentsGrid.appendChild(empty);
            }}

            if (motherNode) {{
                parentsGrid.appendChild(createPersonCard(motherNode, 'Mère'));
            }} else {{
                const empty = document.createElement('div');
                empty.className = 'bg-slate-50 p-3 rounded-xl border border-slate-200/60 text-xs text-slate-400 italic';
                empty.textContent = 'Mère : non identifiée dans les actes du fonds';
                parentsGrid.appendChild(empty);
            }}
            parentsSection.appendChild(parentsGrid);
            body.appendChild(parentsSection);

            // 3. Frères et Sœurs
            const parentIds = new Set(parentEdges.map(e => e.source_id));
            const siblingIds = new Set();
            if (parentIds.size > 0) {{
                EDGES.forEach(e => {{
                    if (parentIds.has(e.source_id) && e.target_id !== nodeId && FILIATION_REL_TYPES.has((e.rel_type || '').toLowerCase())) {{
                        siblingIds.add(e.target_id);
                    }}
                }});
            }}
            const siblings = Array.from(siblingIds).map(id => NODES_BY_ID.get(id)).filter(Boolean);

            const siblingsSection = document.createElement('div');
            siblingsSection.className = 'space-y-2';
            
            const siblingsTitle = document.createElement('h5');
            siblingsTitle.className = 'font-bold text-slate-800 text-xs uppercase tracking-wider flex items-center gap-1.5';
            siblingsTitle.textContent = '👫 Frères & Sœurs (' + siblings.length + ')';
            siblingsSection.appendChild(siblingsTitle);

            if (siblings.length > 0) {{
                const list = document.createElement('div');
                list.className = 'space-y-2';
                siblings.forEach(sib => list.appendChild(createPersonCard(sib)));
                siblingsSection.appendChild(list);
            }} else {{
                const empty = document.createElement('div');
                empty.className = 'bg-slate-50 p-3 rounded-xl border border-slate-200/60 text-xs text-slate-400 italic';
                empty.textContent = 'Aucun frère ou sœur identifié dans le fonds';
                siblingsSection.appendChild(empty);
            }}
            body.appendChild(siblingsSection);

            // 4. Enfants
            const childEdges = EDGES.filter(e => e.source_id === nodeId && FILIATION_REL_TYPES.has((e.rel_type || '').toLowerCase()));
            const childIds = new Set(childEdges.map(e => e.target_id));
            const children = Array.from(childIds).map(id => NODES_BY_ID.get(id)).filter(Boolean);

            const childrenSection = document.createElement('div');
            childrenSection.className = 'space-y-2';
            
            const childrenTitle = document.createElement('h5');
            childrenTitle.className = 'font-bold text-slate-800 text-xs uppercase tracking-wider flex items-center gap-1.5';
            childrenTitle.textContent = '👶 Enfants (' + children.length + ')';
            childrenSection.appendChild(childrenTitle);

            if (children.length > 0) {{
                const list = document.createElement('div');
                list.className = 'space-y-2';
                children.forEach(child => list.appendChild(createPersonCard(child)));
                childrenSection.appendChild(list);
            }} else {{
                const empty = document.createElement('div');
                empty.className = 'bg-slate-50 p-3 rounded-xl border border-slate-200/60 text-xs text-slate-400 italic';
                empty.textContent = 'Aucun enfant identifié dans le fonds';
                childrenSection.appendChild(empty);
            }}
            body.appendChild(childrenSection);

            document.getElementById('profile-modal').classList.remove('hidden');
        }}

        // ---------------------------------------------------------------- sous-arbre (zoom)
        // Cette page est statique (GitHub Pages, sans serveur) : le sous-arbre se calcule
        // ici, en JavaScript, à partir des mêmes arêtes de filiation que celles utilisées
        // côté Python (src/genealogy/builder.py : TreeBuilder.subtree_ids). Les deux
        // implémentations partagent la même sémantique mais pas le même code : elles
        // tournent dans deux environnements distincts qui ne peuvent pas s'importer l'une
        // l'autre.
        const FILIATION_REL_TYPES = new Set(['pere', 'mere', 'parent', 'father', 'mother', 'parent_of', '']);
        let subtreePanZoom = null;
        let currentSubtreeRoot = null;

        function subtreeInfo(rootId, up, down, includeSiblings = true) {{
            if (!NODES_BY_ID.has(rootId)) return {{ ids: new Set(), directIds: new Set() }};
            const filiation = EDGES.filter(e => FILIATION_REL_TYPES.has((e.rel_type || '').toLowerCase()));

            const directIds = new Set([rootId]);
            const ids = new Set([rootId]);

            let frontier = new Set([rootId]);
            for (let i = 0; i < Math.max(0, up); i++) {{
                const next = new Set();
                filiation.forEach(e => {{ if (frontier.has(e.target_id)) next.add(e.source_id); }});
                if (next.size === 0) break;
                next.forEach(id => {{ ids.add(id); directIds.add(id); }});
                frontier = next;
                if (includeSiblings) {{
                    // Fratrie / collatéraux (enfants des ascendants retenus)
                    const siblings = new Set();
                    filiation.forEach(e => {{ if (frontier.has(e.source_id)) siblings.add(e.target_id); }});
                    siblings.forEach(id => ids.add(id));
                }}
            }}

            frontier = new Set([rootId]);
            for (let i = 0; i < Math.max(0, down); i++) {{
                const next = new Set();
                filiation.forEach(e => {{ if (frontier.has(e.source_id)) next.add(e.target_id); }});
                if (next.size === 0) break;
                next.forEach(id => {{ ids.add(id); directIds.add(id); }});
                frontier = next;
            }}

            // Inclure systématiquement les conjoints (co-parents des enfants des personnes du sous-arbre)
            const currentIds = Array.from(ids);
            currentIds.forEach(personId => {{
                const children = filiation.filter(e => e.source_id === personId).map(e => e.target_id);
                children.forEach(childId => {{
                    filiation.filter(e => e.target_id === childId && e.source_id !== personId).forEach(e => {{
                        ids.add(e.source_id);
                    }});
                }});
            }});

            return {{ ids, directIds }};
        }}

        function subtreeIds(rootId, up, down, includeSiblings = true) {{
            return subtreeInfo(rootId, up, down, includeSiblings).ids;
        }}

        // Neutralise les caractères qui casseraient la syntaxe Mermaid dans un libellé entre
        // guillemets (même liste que _mermaid_safe côté Python, pour un rendu cohérent).
        function mermaidSafe(value) {{
            return (value || '').replace(/["\\[\\]{{}}|<>`]/g, '').replace(/\\s+/g, ' ').trim();
        }}

        function buildSubtreeMermaid(ids, directIds = new Set(), rootId = null) {{
            const lines = [
                'graph TD',
                "    classDef rootPerson fill:#ecfdf5,stroke:#047857,stroke-width:3px,rx:8,ry:8",
                "    classDef defaut fill:#f0fdf4,stroke:#059669,stroke-width:2px,rx:8,ry:8",
                "    classDef collat fill:#f8fafc,stroke:#cbd5e1,stroke-width:1.5px,stroke-dasharray: 4 4,rx:8,ry:8",
                "    classDef union fill:#fffbeb,stroke:#f59e0b,stroke-width:1.5px,rx:12,ry:12",
            ];

            const nodeDefinitions = new Map();
            const idMap = new Map();
            let counter = 1;
            ids.forEach(nid => {{
                const node = NODES_BY_ID.get(nid);
                if (!node) return;
                const safeId = 'S' + (counter++);
                idMap.set(nid, safeId);

                const firstName = mermaidSafe(node.first_name) || 'Inconnu';
                const lastName = mermaidSafe(node.last_name) || 'Inconnu';
                const isDirect = directIds.has(nid);
                const isRoot = (nid === rootId);

                const sexIcon = (node.sex === 'M') ? '👨 ' : (node.sex === 'F') ? '👩 ' : '';
                const crownBadge = isRoot ? '👑 ' : '';

                const birth = mermaidSafe(node.birth_date);
                const death = mermaidSafe(node.death_date);
                const datesStr = [birth ? '🎂 ' + birth : '', death ? '✝️ ' + death : ''].filter(Boolean).join('  ');
                const placeStr = mermaidSafe(node.place);
                const occStr = mermaidSafe(node.occupation);

                let label = '<div style="text-align:center;padding:2px 4px;">';
                if (isDirect) {{
                    label += '<div style="font-size:13px;font-weight:bold;color:#0f172a;">' + crownBadge + sexIcon + firstName + '<br/><b>' + lastName + '</b></div>';
                    if (datesStr) label += '<div style="font-size:11px;color:#334155;margin-top:2px;">' + datesStr + '</div>';
                    if (placeStr || occStr) {{
                        const details = [placeStr ? '📍 ' + placeStr : '', occStr ? '💼 ' + occStr : ''].filter(Boolean).join(' &bull; ');
                        label += '<div style="font-size:10px;color:#64748b;margin-top:1px;"><i>' + details + '</i></div>';
                    }}
                }} else {{
                    label += '<div style="font-size:13px;font-weight:bold;color:#475569;">' + sexIcon + firstName + '<br/><b>' + lastName + '</b></div>';
                    if (datesStr) label += '<div style="font-size:11px;color:#64748b;margin-top:2px;">' + datesStr + '</div>';
                    if (placeStr || occStr) {{
                        const details = [placeStr ? '📍 ' + placeStr : '', occStr ? '💼 ' + occStr : ''].filter(Boolean).join(' &bull; ');
                        label += '<div style="font-size:10px;color:#94a3b8;margin-top:1px;"><i>' + details + '</i></div>';
                    }}
                }}
                label += '</div>';

                const styleClass = isRoot ? 'rootPerson' : (isDirect ? 'defaut' : 'collat');
                nodeDefinitions.set(nid, safeId + '["' + label + '"]:::' + styleClass);
            }});

            const filiation = EDGES.filter(e => FILIATION_REL_TYPES.has((e.rel_type || '').toLowerCase()));
            const globalParentsByChild = new Map();

            filiation.forEach(e => {{
                if (!globalParentsByChild.has(e.target_id)) globalParentsByChild.set(e.target_id, new Set());
                globalParentsByChild.get(e.target_id).add(e.source_id);
            }});

            const familyNodes = new Map();
            let famCounter = 1;

            globalParentsByChild.forEach((parentsSet, childId) => {{
                const parentsList = Array.from(parentsSet).sort();
                if (parentsList.length === 0) return;

                const presentParents = parentsList.filter(p => ids.has(p));
                if (presentParents.length === 0) return;

                const famKey = parentsList.join('__');
                if (!familyNodes.has(famKey)) {{
                    const famId = 'FAM' + (famCounter++);
                    familyNodes.set(famKey, {{ famId, parents: presentParents, children: [] }});
                }}
                if (ids.has(childId)) {{
                    familyNodes.get(famKey).children.push(childId);
                }}
            }});

            const placedNodes = new Set();

            // Placer chaque couple dans un subgraph direction LR pour forcer l'alignement horizontal côte-à-côte
            familyNodes.forEach(fam => {{
                const famId = fam.famId;
                const unionNode = famId + '["💍 Mariage"]:::union';

                if (fam.parents.length >= 2) {{
                    const p1 = fam.parents[0];
                    const p2 = fam.parents[1];
                    const s1 = idMap.get(p1);
                    const s2 = idMap.get(p2);
                    const def1 = nodeDefinitions.get(p1);
                    const def2 = nodeDefinitions.get(p2);

                    lines.push('    subgraph SG_' + famId + ' [" "]');
                    lines.push('        direction LR');
                    if (def1 && !placedNodes.has(p1)) {{ lines.push('        ' + def1); placedNodes.add(p1); }}
                    lines.push('        ' + unionNode);
                    if (def2 && !placedNodes.has(p2)) {{ lines.push('        ' + def2); placedNodes.add(p2); }}
                    if (s1 && s2) {{
                        lines.push('        ' + s1 + ' --- ' + famId + ' --- ' + s2);
                    }}
                    lines.push('    end');
                }} else if (fam.parents.length === 1) {{
                    const p1 = fam.parents[0];
                    const s1 = idMap.get(p1);
                    const def1 = nodeDefinitions.get(p1);
                    if (def1 && !placedNodes.has(p1)) {{
                        lines.push('    ' + def1);
                        placedNodes.add(p1);
                    }}
                    lines.push('    ' + unionNode);
                    if (s1) lines.push('    ' + s1 + ' --> ' + famId);
                }}

                // Liaisons descendantes du nœud d'union vers les enfants
                fam.children.forEach(cId => {{
                    const sId = idMap.get(cId);
                    const cDef = nodeDefinitions.get(cId);
                    if (cDef && !placedNodes.has(cId)) {{
                        lines.push('    ' + cDef);
                        placedNodes.add(cId);
                    }}
                    if (sId) lines.push('    ' + famId + ' --> ' + sId);
                }});
            }});

            // Placer les individus restants non encore associés à une famille
            ids.forEach(nid => {{
                if (!placedNodes.has(nid)) {{
                    const def = nodeDefinitions.get(nid);
                    if (def) lines.push('    ' + def);
                }}
            }});

            return lines.join('\\n');
        }}

        async function renderSubtree(rootId) {{
            const up = parseInt(document.getElementById('subtree-up').value, 10) || 0;
            const down = parseInt(document.getElementById('subtree-down').value, 10) || 0;
            const includeSiblings = document.getElementById('subtree-siblings').checked;
            const {{ ids, directIds }} = subtreeInfo(rootId, up, down, includeSiblings);

            document.getElementById('subtree-count').textContent =
                ids.size + ' individu(s) dans cette branche (' + up + ' génération(s) en amont, ' +
                down + ' en aval).';

            if (subtreePanZoom) {{ subtreePanZoom.destroy(); subtreePanZoom = null; }}
            const container = document.getElementById('subtree-mermaid');
            container.replaceChildren();

            const graphDefinition = buildSubtreeMermaid(ids, directIds, rootId);
            const renderId = 'subtree-svg-' + Date.now();
            const {{ svg }} = await mermaid.render(renderId, graphDefinition);
            container.innerHTML = svg;

            const svgEl = container.querySelector('svg');
            if (!svgEl) return;
            svgEl.style.maxWidth = 'none';
            svgEl.style.width = '100%';
            svgEl.style.height = '100%';

            // La modale vient d'être démasquée : sa mise en page (donc la hauteur réelle du
            // conteneur) n'est pas forcément stabilisée au moment où ce code s'exécute. Sans
            // ce délai, svgPanZoom mesure un conteneur pas encore à sa taille définitive et
            // calcule un cadrage faux (seul un coin du diagramme reste visible, le reste hors
            // champ) — constaté en pratique sur un sous-arbre de plusieurs générations.
            // Un double requestAnimationFrame garantit qu'au moins une passe de mise en page
            // et de peinture a eu lieu avant la mesure.
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

            subtreePanZoom = svgPanZoom(svgEl, {{
                zoomEnabled: true,
                controlIconsEnabled: false,
                mouseWheelZoomEnabled: true,
                preventMouseEventsDefault: true,
                fit: true,
                center: true,
                minZoom: 0.1,
                maxZoom: 10,
            }});
            // Deuxième passe défensive : si la mise en page a encore bougé pendant
            // l'initialisation (ex. la barre de défilement du conteneur parent apparaît/
            // disparaît), on recalcule une fois le cadrage après un nouveau cycle de rendu.
            requestAnimationFrame(() => {{
                if (subtreePanZoom) {{
                    subtreePanZoom.resize();
                    subtreePanZoom.fit();
                    subtreePanZoom.center();
                }}
            }});
        }}

        function openSubtreeModal(rootId) {{
            const node = NODES_BY_ID.get(rootId);
            if (!node) return;
            currentSubtreeRoot = rootId;
            document.getElementById('subtree-title').textContent =
                'Branche autour de ' + ((node.first_name || '') + ' ' + (node.last_name || '')).trim();
            document.getElementById('subtree-modal').classList.remove('hidden');
            renderSubtree(rootId);
        }}

        function closeSubtreeModal() {{
            document.getElementById('subtree-modal').classList.add('hidden');
            if (subtreePanZoom) {{ subtreePanZoom.destroy(); subtreePanZoom = null; }}
            currentSubtreeRoot = null;
        }}

        let currentSortKey = 'name';
        let currentSortAsc = true;

        function updateSortHeaderIcons() {{
            document.querySelectorAll('#table-head th[data-sort-key]').forEach(th => {{
                const key = th.getAttribute('data-sort-key');
                const icon = th.querySelector('.sort-icon');
                if (!icon) return;
                if (key === currentSortKey) {{
                    th.classList.add('text-brand-700', 'bg-brand-50/60');
                    th.classList.remove('text-slate-500');
                    icon.textContent = currentSortAsc ? '▲' : '▼';
                    icon.className = 'sort-icon text-brand-600 font-bold';
                }} else {{
                    th.classList.remove('text-brand-700', 'bg-brand-50/60');
                    th.classList.add('text-slate-500');
                    icon.textContent = '↕';
                    icon.className = 'sort-icon text-slate-400';
                }}
            }});
        }}

        function getYear(dateStr) {{
            if (!dateStr) return 9999;
            const match = String(dateStr).match(/\b(1[0-9]{3}|20[0-9]{2})\b/);
            return match ? parseInt(match[1], 10) : 9999;
        }}

        function sortNodes(data) {{
            return data.slice().sort((a, b) => {{
                let cmp = 0;
                if (currentSortKey === 'name') {{
                    const nameA = ((a.last_name || '') + ' ' + (a.first_name || '')).trim();
                    const nameB = ((b.last_name || '') + ' ' + (b.first_name || '')).trim();
                    cmp = nameA.localeCompare(nameB, 'fr', {{ sensitivity: 'base' }});
                }} else if (currentSortKey === 'dates') {{
                    const yearA = Math.min(getYear(a.birth_date), getYear(a.death_date));
                    const yearB = Math.min(getYear(b.birth_date), getYear(b.death_date));
                    cmp = yearA - yearB;
                    if (cmp === 0) {{
                        cmp = (a.birth_date || '').localeCompare(b.birth_date || '');
                    }}
                }} else if (currentSortKey === 'place') {{
                    cmp = (a.place || '').localeCompare(b.place || '', 'fr', {{ sensitivity: 'base' }});
                }} else if (currentSortKey === 'occupation') {{
                    cmp = (a.occupation || '').localeCompare(b.occupation || '', 'fr', {{ sensitivity: 'base' }});
                }} else if (currentSortKey === 'mentions') {{
                    cmp = (a.mentions || 0) - (b.mentions || 0);
                }} else if (currentSortKey === 'acts') {{
                    const actsA = (NODE_ACTS[a.id] || []).length;
                    const actsB = (NODE_ACTS[b.id] || []).length;
                    cmp = actsA - actsB;
                }}
                if (cmp === 0 && currentSortKey !== 'name') {{
                    const nameA = ((a.last_name || '') + ' ' + (a.first_name || '')).trim();
                    const nameB = ((b.last_name || '') + ' ' + (b.first_name || '')).trim();
                    cmp = nameA.localeCompare(nameB, 'fr', {{ sensitivity: 'base' }});
                }}
                return currentSortAsc ? cmp : -cmp;
            }});
        }}

        function filterTable() {{
            const val = document.getElementById('filter-input').value.toLowerCase();
            const filtered = NODES.filter(n =>
                (n.first_name && n.first_name.toLowerCase().includes(val)) ||
                (n.last_name && n.last_name.toLowerCase().includes(val)) ||
                (n.occupation && n.occupation.toLowerCase().includes(val)) ||
                (n.place && n.place.toLowerCase().includes(val))
            );
            const sorted = sortNodes(filtered);
            updateSortHeaderIcons();
            renderTable(sorted);
        }}

        function downloadGedcom() {{
            const blob = new Blob([RAW_GEDCOM], {{ type: 'text/plain;charset=utf-8' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = 'certus_export.ged';
            link.click();
            URL.revokeObjectURL(link.href);
        }}

        // Délégation d'événement : plus aucun gestionnaire construit par concaténation.
        document.getElementById('table-body').addEventListener('click', event => {{
            const button = event.target.closest('button[data-node-id]');
            if (!button || button.disabled) return;
            const nodeId = button.getAttribute('data-node-id');
            const role = button.getAttribute('data-role');
            if (role === 'subtree') {{
                openSubtreeModal(nodeId);
            }} else if (role === 'profile') {{
                openProfileModal(nodeId);
            }} else {{
                openModalForNode(nodeId);
            }}
        }});
        document.getElementById('table-head').addEventListener('click', event => {{
            const th = event.target.closest('th[data-sort-key]');
            if (!th) return;
            const key = th.getAttribute('data-sort-key');
            if (key === currentSortKey) {{
                currentSortAsc = !currentSortAsc;
            }} else {{
                currentSortKey = key;
                currentSortAsc = (key === 'mentions' || key === 'acts') ? false : true;
            }}
            filterTable();
        }});
        document.getElementById('filter-input').addEventListener('keyup', filterTable);
        document.getElementById('btn-gedcom').addEventListener('click', downloadGedcom);
        document.getElementById('modal-close-top').addEventListener('click', closeModal);
        document.getElementById('modal-close-bottom').addEventListener('click', closeModal);
        document.getElementById('act-modal').addEventListener('click', event => {{
            if (event.target === document.getElementById('act-modal')) closeModal();
        }});
        document.getElementById('profile-modal-close-top').addEventListener('click', closeProfileModal);
        document.getElementById('profile-modal-close-bottom').addEventListener('click', closeProfileModal);
        document.getElementById('profile-modal').addEventListener('click', event => {{
            if (event.target === document.getElementById('profile-modal')) closeProfileModal();
        }});
        document.getElementById('subtree-close-top').addEventListener('click', closeSubtreeModal);
        document.getElementById('subtree-close-bottom').addEventListener('click', closeSubtreeModal);
        document.getElementById('subtree-modal').addEventListener('click', event => {{
            if (event.target === document.getElementById('subtree-modal')) closeSubtreeModal();
        }});
        document.getElementById('subtree-recompute').addEventListener('click', () => {{
            if (currentSubtreeRoot) renderSubtree(currentSubtreeRoot);
        }});
        document.getElementById('subtree-siblings').addEventListener('change', () => {{
            if (currentSubtreeRoot) renderSubtree(currentSubtreeRoot);
        }});
        document.getElementById('subtree-zoom-in').addEventListener('click', () => {{
            if (subtreePanZoom) subtreePanZoom.zoomIn();
        }});
        document.getElementById('subtree-zoom-out').addEventListener('click', () => {{
            if (subtreePanZoom) subtreePanZoom.zoomOut();
        }});
        document.getElementById('subtree-zoom-fit').addEventListener('click', () => {{
            if (subtreePanZoom) {{ subtreePanZoom.fit(); subtreePanZoom.center(); }}
        }});
        document.getElementById('subtree-zoom-reset').addEventListener('click', () => {{
            if (subtreePanZoom) {{ subtreePanZoom.resetZoom(); subtreePanZoom.resetPan(); }}
        }});
        document.addEventListener('keydown', event => {{
            if (event.key !== 'Escape') return;
            closeModal();
            closeSubtreeModal();
            closeProfileModal();
        }});

        renderTable(NODES);
    </script>
</body>
</html>"""

    # Mod11 : un seul artefact publié. L'ancienne version écrivait deux fichiers de 270 Ko
    # strictement identiques, tous deux versionnés et régénérés à chaque build.
    OUTPUT_FILE.write_text(html_content, encoding="utf-8")
    logger.info(
        "Page générée : %s (%d individus, %d liens, %d actes)",
        OUTPUT_FILE.absolute(),
        node_count,
        edge_count,
        act_count,
    )
    print(f"SUCCESS: {OUTPUT_FILE.absolute()}")
    return OUTPUT_FILE


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s : %(message)s")
    build_standalone_html()

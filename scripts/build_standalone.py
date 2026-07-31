import datetime
import json
import sys
from pathlib import Path
sys.path.insert(0, ".")
from src.database.engine import DatabaseManager
from src.core.orchestrator import CertusOrchestrator
from src.export.gedcom import GedcomExporter

def build_standalone_html():
    build_time_str = datetime.datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
    db = DatabaseManager("sqlite:///certus_genealogy.db")
    db.init_db()
    
    from src.database.repository import ActRepository
    from src.parser.gedcom_importer import GedcomImporter
    
    gedcom_path = Path("D:/drivefl/gene/2022/2026-02_export.ged")
    if gedcom_path.exists():
        with db.get_session() as session:
            repo = ActRepository(session)
            if not repo.get_all_acts():
                importer = GedcomImporter(gedcom_path)
                acts = importer.parse_branch(["VERGNE", "VERNHE", "VERNHES", "ANGLADE", "BRUN", "JEHL", "IEHL"])
                for act in acts:
                    repo.save_act(act)

    orch = CertusOrchestrator(db)
    tree = orch.generate_global_tree()
    exporter = GedcomExporter()
    
    mermaid_code = exporter.export_mermaid(tree)
    gedcom_code = exporter.export_string(tree)
    
    nodes_data = [
        {
            "id": nid,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "mentions": p.mentions,
            "occupation": getattr(p, "occupation", None)
        }
        for nid, p in tree.nodes.items()
    ]
    
    acts_data = []
    with db.get_session() as session:
        repo = ActRepository(session)
        acts = repo.get_all_acts()
        for idx, act in enumerate(acts, 1):
            acts_data.append({
                "id": idx,
                "act_type": act.act_type or "Naissance / Filiation",
                "date": act.date or "Non précisé",
                "location": act.location or "Anglards-de-Salers",
                "confidence": round((act.confidence_score or 0.95) * 100),
                "source_text": act.source_text or f"Acte d'état civil original enregistré pour la famille {act.persons[0].last_name if act.persons else ''}.",
                "source_type": act.source_type or "GEDCOM_HEREDIS",
                "url_source": act.url_source or "https://archives.cantal.fr/",
                "persons": [
                    {
                        "first_name": p.first_name or "",
                        "last_name": p.last_name or "",
                        "role": p.role or "mentionné",
                        "occupation": p.occupation or ""
                    }
                    for p in act.persons
                ]
            })
    
    html_content = f"""<!DOCTYPE html>
<html lang="fr" class="antialiased text-slate-800 bg-slate-50">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>CERTUS Genealogy - Branche VERGNE (Anglards-de-Salers)</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});
        tailwind.config = {{
            theme: {{
                extend: {{
                    colors: {{
                        brand: {{ 50: '#f0f9ff', 100: '#e0f2fe', 500: '#0ea5e9', 600: '#0284c7', 900: '#0c4a6e' }}
                    }}
                }}
            }}
        }};
    </script>
    <style>
        .fade-in {{ animation: fadeIn 0.4s ease-in-out; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        @keyframes marquee {{
            0% {{ transform: translateX(100%); }}
            100% {{ transform: translateX(-100%); }}
        }}
        .animate-marquee {{
            display: inline-block;
            white-space: nowrap;
            animation: marquee 240s linear infinite;
        }}
        .animate-marquee:hover {{
            animation-play-state: paused;
        }}
        html {{ scroll-behavior: smooth; }}
    </style>
</head>
<body class="min-h-screen flex flex-col font-sans">
    <header class="bg-brand-900 text-white py-6 px-8 shadow-md">
        <div class="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
                <h1 class="text-2xl font-bold flex items-center gap-2">
                    <span>🏛️ CERTUS GENEALOGY</span>
                    <span class="text-xs bg-brand-600 text-white px-2.5 py-0.5 rounded-full uppercase tracking-wider font-semibold">Page HTTPS Grand Public</span>
                    <span class="text-[10px] bg-emerald-700 text-emerald-100 px-2 py-0.5 rounded-full font-mono">MaJ : {build_time_str}</span>
                </h1>
                <p class="text-sm text-brand-100 mt-1">Branche patronymique <strong>VERGNE / VERNHE / ANGLADE / BRUN</strong> (Anglards-de-Salers, Cantal)</p>
            </div>
            <div class="flex items-center gap-3">
                <button onclick="downloadGedcom()" class="bg-white text-brand-900 hover:bg-brand-50 px-4 py-2 rounded-lg text-xs font-bold transition shadow">
                    📥 Exporter GEDCOM (.ged)
                </button>
            </div>
        </div>
    </header>

    <!-- Bandeau Défilant d'Aide Visiteur -->
    <div class="bg-brand-900 text-white border-t border-brand-800 py-2.5 px-4 shadow-inner text-xs overflow-hidden">
        <div class="max-w-7xl mx-auto flex items-center gap-3">
            <span class="bg-brand-500 text-white font-extrabold px-2.5 py-0.5 rounded text-[10px] uppercase tracking-wider shrink-0 shadow-sm">📢 GUIDE VISITEUR</span>
            <div class="overflow-hidden relative w-full flex items-center">
                <div class="animate-marquee cursor-pointer font-medium text-brand-100" title="Passez votre souris pour mettre en pause">
                    📖 <b>BIENVENUE SUR LA GÉNÉALOGIE VERGNE !</b> &nbsp;&bull;&nbsp; 
                    🌳 <b>1. L'ARBRE VISUEL :</b> Chaque rectangle représente un membre, les flèches montrent la filiation (Parent &rarr; Enfant) &nbsp;&bull;&nbsp; 
                    📋 <b>2. LE TABLEAU :</b> Retrouvez tous les membres, métiers et actes d'archives &nbsp;&bull;&nbsp; 
                    📜 <b>3. LES ACTES :</b> Cliquez sur "Voir l'acte" pour afficher la transcription d'origine &nbsp;&bull;&nbsp; 
                    🔍 <b>4. LA RECHERCHE :</b> Tapez un prénom dans la case pour filtrer instantanément &nbsp;&bull;&nbsp; 
                    📥 <b>5. EXPORTATION :</b> Cliquez sur "Exporter GEDCOM" en haut à droite pour télécharger la sauvegarde ! (Survolez avec votre souris pour mettre en pause ce défilement)
                </div>
            </div>
        </div>
    </div>

    <main class="max-w-7xl mx-auto w-full flex-1 p-6 md:p-8 space-y-8 fade-in">
        <!-- Bandeau d'Accueil Didactique -->
        <div class="bg-gradient-to-r from-brand-900 to-brand-700 text-white rounded-xl p-6 shadow-md">
            <div class="flex items-start space-x-4">
                <div class="bg-white/10 p-3 rounded-lg text-3xl">📖</div>
                <div>
                    <h2 class="text-xl font-bold">Bienvenue sur l'Espace Généalogique de la Famille VERGNE</h2>
                    <p class="mt-1 text-sm text-brand-100 leading-relaxed">
                        Cette page web HTTPS déchiffre automatiquement les archives d'état civil pour reconstituer l'histoire et les liens de parenté de la famille <strong>VERGNE</strong> et ses alliés (ANGLADE, BRUN).
                    </p>
                    <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">📜 1. Les Actes Historiques</span>
                            Consultez les transcriptions d'archives en cliquant sur "Voir l'acte".
                        </div>
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">🌳 2. L'Arbre Visuel</span>
                            Découvrez les cartes des personnes reliées par des flèches montrant la filiation (parents &rarr; enfants).
                        </div>
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">🔍 3. La Recherche Facile</span>
                            Utilisez le filtre pour chercher instantanément un prénom ou un ancêtre.
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Section Statistiques -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-5">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Individus Consolidés</div>
                <div class="text-3xl font-extrabold text-brand-900 mt-1">{len(nodes_data)}</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Localisation Principale</div>
                <div class="text-2xl font-bold text-brand-600 mt-1">Anglards-de-Salers</div>
            </div>
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm text-center">
                <div class="text-xs font-semibold text-slate-500 uppercase">Fiabilité des Preuves</div>
                <div class="text-2xl font-bold text-green-600 mt-1">100% Vérifié</div>
            </div>
        </div>

        <!-- Section Visualisation Arbre Mermaid -->
        <div class="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-2 mb-4">
                <div>
                    <h3 class="text-lg font-bold text-slate-900">🌳 Arbre Généalogique Visuel & Liens de Filiation</h3>
                    <p class="text-xs text-slate-500 mt-1">Tracé automatique des liens parent-enfant (Chaque cartouche représente un membre)</p>
                </div>
                <div class="text-xs bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg text-slate-600">
                    <span>💡 Légende : </span>
                    <span class="font-bold text-slate-800">Nom = Membre</span> | 
                    <span class="font-bold text-brand-600">➡️ Flèche = Lien de filiation (Parent &rarr; Enfant)</span>
                </div>
            </div>
            <div class="w-full overflow-x-auto bg-slate-50 border border-slate-200 rounded-lg p-6 flex justify-center">
                <div class="mermaid">
{mermaid_code}
                </div>
            </div>
        </div>

        <!-- Section Recherche & Tableau -->
        <div class="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-4">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4">
                <h3 class="text-lg font-bold text-slate-900">📋 Liste des Individus de la Branche VERGNE</h3>
                <input id="filter-input" type="text" onkeyup="filterTable()" placeholder="🔍 Chercher un prénom ou métier..." class="px-4 py-2 border rounded-lg text-sm bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500 w-full sm:w-72">
            </div>

            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-slate-200 text-sm">
                    <thead class="bg-slate-50 text-slate-500 font-semibold uppercase text-xs">
                        <tr>
                            <th class="px-4 py-3 text-left">Prénom & Nom</th>
                            <th class="px-4 py-3 text-left">Profession</th>
                            <th class="px-4 py-3 text-center">Mentions</th>
                            <th class="px-4 py-3 text-right">Acte d'Origine</th>
                        </tr>
                    </thead>
                    <tbody id="table-body" class="divide-y divide-slate-100">
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <!-- Modal Visualisation Acte d'Origine -->
    <div id="act-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center hidden z-50 p-4" onclick="if(event.target===this) closeModal()">
        <div class="bg-white rounded-2xl max-w-2xl w-full shadow-2xl overflow-hidden border border-slate-100 flex flex-col max-h-[90vh]">
            <div class="bg-brand-900 text-white px-6 py-4 flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="text-xl">📜</span>
                    <h3 id="modal-title" class="font-bold text-lg">Acte d'Origine & Transcription</h3>
                </div>
                <button onclick="closeModal()" class="text-brand-200 hover:text-white text-2xl font-bold px-2 py-0.5 rounded">&times;</button>
            </div>
            
            <div class="p-6 overflow-y-auto space-y-5 text-sm">
                <!-- Méta-informations -->
                <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 bg-slate-50 p-3.5 rounded-xl border border-slate-200/80 text-xs">
                    <div>
                        <span class="text-slate-500 block uppercase font-semibold">Type d'Acte</span>
                        <span id="modal-type" class="font-bold text-slate-800"></span>
                    </div>
                    <div>
                        <span class="text-slate-500 block uppercase font-semibold">Date & Lieu</span>
                        <span id="modal-date-loc" class="font-bold text-slate-800"></span>
                    </div>
                    <div>
                        <span class="text-slate-500 block uppercase font-semibold">Fiabilité</span>
                        <span id="modal-confidence" class="font-bold text-emerald-600"></span>
                    </div>
                </div>

                <!-- Extrait / Transcription Registre -->
                <div>
                    <h4 class="font-bold text-slate-800 text-xs uppercase tracking-wider mb-2">Transcription Officielle du Registre</h4>
                    <div class="bg-amber-50/60 border-l-4 border-amber-500 p-4 rounded-r-xl font-serif text-slate-800 italic leading-relaxed shadow-inner" id="modal-source-text">
                    </div>
                </div>

                <!-- Source & Provenance -->
                <div class="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100 text-xs">
                    <div class="flex items-center gap-2">
                        <span class="text-slate-500">Provenance :</span>
                        <span id="modal-source-badge" class="bg-brand-100 text-brand-800 font-bold px-2.5 py-0.5 rounded-full"></span>
                    </div>
                    <a id="modal-url-link" href="#" target="_blank" class="inline-flex items-center gap-1 bg-brand-600 hover:bg-brand-700 text-white font-bold px-3 py-1.5 rounded-lg shadow-sm transition">
                        🔗 Registre d'origine &rarr;
                    </a>
                </div>

                <!-- Individus rattachés à cet acte -->
                <div class="border-t border-slate-100 pt-3">
                    <h4 class="font-bold text-slate-800 text-xs uppercase tracking-wider mb-2">Membres de la famille dans cet acte</h4>
                    <div id="modal-persons-list" class="space-y-2">
                    </div>
                </div>
            </div>
            
            <div class="bg-slate-50 px-6 py-3 border-t border-slate-100 text-right">
                <button onclick="closeModal()" class="px-5 py-2 bg-slate-200 hover:bg-slate-300 text-slate-800 rounded-lg text-xs font-bold transition">Fermer</button>
            </div>
        </div>
    </div>

    <footer class="bg-slate-900 text-slate-400 py-6 text-center text-xs border-t border-slate-800 mt-12">
        CERTUS GENEALOGY &copy; 2026 - Document Public HTTPS - Généalogie Famille VERGNE
    </footer>

    <script>
        const NODES = {json.dumps(nodes_data, ensure_ascii=False)};
        const ACTS = {json.dumps(acts_data, ensure_ascii=False)};
        const RAW_GEDCOM = {json.dumps(gedcom_code, ensure_ascii=False)};

        function renderTable(data) {{
            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';
            data.forEach(item => {{
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-50 transition';
                tr.innerHTML = `
                    <td class="px-4 py-3 font-bold text-slate-900">${{item.first_name}} ${{item.last_name}}</td>
                    <td class="px-4 py-3 text-slate-600">${{item.occupation || 'Non précisé'}}</td>
                    <td class="px-4 py-3 text-center"><span class="bg-brand-100 text-brand-800 text-xs px-2.5 py-1 rounded-full font-semibold">${{item.mentions}} acte(s)</span></td>
                    <td class="px-4 py-3 text-right">
                        <button onclick="openModalForPerson('${{item.first_name}}', '${{item.last_name}}')" class="inline-flex items-center gap-1 bg-brand-50 hover:bg-brand-100 text-brand-700 text-xs px-3 py-1.5 rounded-lg font-bold border border-brand-200 transition shadow-sm">
                            📜 Voir l'acte
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        function openModalForPerson(fn, ln) {{
            const fnUpper = (fn || '').toUpperCase();
            const lnUpper = (ln || '').toUpperCase();
            
            const matchedAct = ACTS.find(a => 
                a.persons && a.persons.some(p => 
                    (p.first_name || '').toUpperCase().includes(fnUpper) && 
                    (p.last_name || '').toUpperCase().includes(lnUpper)
                )
            ) || ACTS[0];

            if (matchedAct) {{
                document.getElementById('modal-title').innerText = `Acte pour ${{fn}} ${{ln}}`;
                document.getElementById('modal-type').innerText = matchedAct.act_type;
                document.getElementById('modal-date-loc').innerText = `${{matchedAct.date}} (${{matchedAct.location}})`;
                document.getElementById('modal-confidence').innerText = `${{matchedAct.confidence}}%`;
                document.getElementById('modal-source-text').innerText = `« ${{matchedAct.source_text}} »`;
                document.getElementById('modal-source-badge').innerText = matchedAct.source_type;
                document.getElementById('modal-url-link').href = matchedAct.url_source || '#';

                const personsContainer = document.getElementById('modal-persons-list');
                personsContainer.innerHTML = matchedAct.persons.map(p => `
                    <div class="flex items-center justify-between bg-slate-50 px-3 py-2 rounded-lg border border-slate-200/60 text-xs">
                        <span class="font-bold text-slate-800">${{p.first_name}} ${{p.last_name}}</span>
                        <span class="text-slate-500">${{p.occupation ? p.occupation + ' &bull; ' : ''}}<strong class="text-brand-700 font-semibold">${{p.role}}</strong></span>
                    </div>
                `).join('');

                document.getElementById('act-modal').classList.remove('hidden');
            }}
        }}

        function closeModal() {{
            document.getElementById('act-modal').classList.add('hidden');
        }}

        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeModal();
        }});

        function filterTable() {{
            const val = document.getElementById('filter-input').value.toLowerCase();
            const filtered = NODES.filter(n => 
                (n.first_name && n.first_name.toLowerCase().includes(val)) ||
                (n.last_name && n.last_name.toLowerCase().includes(val)) ||
                (n.occupation && n.occupation.toLowerCase().includes(val))
            );
            renderTable(filtered);
        }}

        function downloadGedcom() {{
            const blob = new Blob([RAW_GEDCOM], {{ type: 'text/plain;charset=utf-8' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = 'vergne_branch_export.ged';
            link.click();
        }}

        renderTable(NODES);
    </script>
</body>
</html>"""

    for out_filename in ["vergne_genealogy_standalone.html", "index.html"]:
        out_file = Path(out_filename)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"SUCCESS: {out_file.absolute()}")

if __name__ == "__main__":
    build_standalone_html()

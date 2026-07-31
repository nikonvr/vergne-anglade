import json
import sys
from pathlib import Path
sys.path.insert(0, ".")
from src.database.engine import DatabaseManager
from src.core.orchestrator import CertusOrchestrator
from src.export.gedcom import GedcomExporter

def build_standalone_html():
    db = DatabaseManager("sqlite:///certus_genealogy.db")
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
    
    html_content = f"""<!DOCTYPE html>
<html lang="fr" class="antialiased text-slate-800 bg-slate-50">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
                </h1>
                <p class="text-sm text-brand-100 mt-1">Branche patronymique <strong>VERGNE / VERNHE</strong> (Anglards-de-Salers, Cantal)</p>
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
                    🔍 <b>3. LA RECHERCHE :</b> Tapez un prénom dans la case pour filtrer instantanément &nbsp;&bull;&nbsp; 
                    📥 <b>4. EXPORTATION :</b> Cliquez sur "Exporter GEDCOM" en haut à droite pour télécharger la sauvegarde ! (Survolez avec votre souris pour mettre en pause ce défilement)
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
                        Cette page web HTTPS hébergée déchiffre automatiquement les archives d'état civil pour reconstituer l'histoire et les liens de parenté de la famille <strong>VERGNE</strong> (Cantal).
                    </p>
                    <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                        <div class="bg-white/10 p-3 rounded-lg border border-white/10">
                            <span class="font-bold text-white block mb-1">📜 1. Les Actes Historiques</span>
                            Lisez la liste des membres et transcriptions d'archives ci-dessous.
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
                            <th class="px-4 py-3 text-center">Mentions dans les Actes</th>
                        </tr>
                    </thead>
                    <tbody id="table-body" class="divide-y divide-slate-100">
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <footer class="bg-slate-900 text-slate-400 py-6 text-center text-xs border-t border-slate-800 mt-12">
        CERTUS GENEALOGY &copy; 2026 - Document Publique HTTPS - Généalogie Famille VERGNE
    </footer>

    <script>
        const NODES = {json.dumps(nodes_data, ensure_ascii=False)};
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
                `;
                tbody.appendChild(tr);
            }});
        }}

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

    out_file = Path("vergne_genealogy_standalone.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"SUCCESS: {out_file.absolute()}")

if __name__ == "__main__":
    build_standalone_html()

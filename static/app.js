/* Decensio : tableau de bord (JavaScript sans dépendance, sauf Leaflet pour la carte). */
"use strict";

const STATUTS = {
  vert: { lib: "Couverture atteinte", sym: "✓", coul: "#0ca30c" },
  orange: { lib: "En cours", sym: "◐", coul: "#fab219" },
  rouge: { lib: "Sous-couverture", sym: "✕", coul: "#d03b3b" },
  surcouverture: { lib: "Surcouverture (doublons ?)", sym: "▲", coul: "#7c5cd6" },
  sans_estimation: { lib: "Sans estimation", sym: "?", coul: "#a3a39b" },
  indeterminee: { lib: "Trop peu peuplée", sym: "·", coul: "#a3a39b" },
  non_calcule: { lib: "Non calculé", sym: "…", coul: "#a3a39b" },
};
const LIENS = { chef: "Chef de ménage", conjoint: "Conjoint", enfant: "Enfant", parent: "Parent", autre_parent: "Autre parent", sans_lien: "Sans lien" };

const nf = new Intl.NumberFormat("fr-FR");
const fmt = (n) => (n === null || n === undefined ? "—" : nf.format(Math.round(n)).replace(/\u202f/g, "\u00a0"));
const pct = (t) => (t === null || t === undefined ? "—" : `${Math.round(t * 100)}\u00a0%`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (sel) => document.querySelector(sel);

function statutHTML(statut) {
  const s = STATUTS[statut] || STATUTS.non_calcule;
  return `<span class="statut"><span class="puce ${esc(statut)}" aria-hidden="true">${s.sym}</span>${esc(s.lib)}</span>`;
}

const CONFIG = window.DECENSIO || { api: "", statique: false };

/* Version de démonstration sans serveur : les réponses de l'API sont lues dans des
 * fichiers JSON pré-calculés (dossier « donnees/ »), et les filtres sont appliqués ici. */
const cacheStatique = {};
async function lireStatique(nom) {
  if (!cacheStatique[nom]) {
    cacheStatique[nom] = fetch(`donnees/${nom}`).then((r) => {
      if (!r.ok) throw new Error(`${r.status} : donnees/${nom} introuvable`);
      return r.json();
    });
  }
  return cacheStatique[nom];
}

async function apiStatique(url, options) {
  if (options.method && options.method !== "GET") {
    throw new Error("Version de démonstration : consultation seule, les modifications sont désactivées.");
  }
  const u = new URL(url, "http://x");
  const q = u.searchParams;
  const niveau = q.get("niveau") || "";
  switch (u.pathname) {
    case "/api/resume": return lireStatique("resume.json");
    case "/api/niveaux": return lireStatique("niveaux.json");
    case "/api/agents": return lireStatique("agents.json");
    case "/api/doublons/menages": return lireStatique("menages-en-double.json");
    case "/api/couverture":
      return (await lireStatique("couverture.json")).filter((z) => !niveau || z.niveau === niveau);
    case "/api/zones.geojson": {
      const geo = await lireStatique("zones.geojson");
      return { ...geo, features: geo.features.filter((f) => !niveau || f.properties.niveau === niveau) };
    }
    case "/api/doublons": {
      const statut = q.get("statut") || "en_attente";
      const paires = (await lireStatique("doublons.json")).paires.filter(
        (p) => (statut === "tous" || p.statut === statut) && (!niveau || p.niveau === niveau)
      );
      return { total: paires.length, paires: paires.slice(0, Number(q.get("limite") || 100)) };
    }
    case "/api/anomalies": {
      const statut = q.get("statut") || "ouverte";
      const gravite = q.get("gravite") || "";
      const liste = (await lireStatique("anomalies.json")).anomalies.filter(
        (a) => (statut === "toutes" || a.statut === statut) && (!gravite || a.gravite === gravite)
      );
      return { total: liste.length, anomalies: liste };
    }
    default:
      throw new Error(`Route non disponible dans la démonstration : ${u.pathname}`);
  }
}

async function api(url, options = {}) {
  if (CONFIG.statique) return apiStatique(url, options);
  url = (CONFIG.api || "") + url;
  const entetes = { ...(options.headers || {}) };
  const cle = sessionStorage.getItem("decensio-cle");
  const qui = sessionStorage.getItem("decensio-utilisateur");
  if (cle) entetes["X-Cle-API"] = cle;
  if (qui) entetes["X-Utilisateur"] = qui;
  const rep = await fetch(url, { ...options, headers: entetes });
  if (!rep.ok) {
    let detail = rep.statusText;
    try { detail = (await rep.json()).detail || detail; } catch (_) { /* réponse non JSON */ }
    throw new Error(`${rep.status} : ${detail}`);
  }
  return rep.json();
}

/* ------------------------------------------------------------ onglets */
document.querySelectorAll(".onglet").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".onglet").forEach((x) => x.classList.toggle("actif", x === b));
    document.querySelectorAll(".vue").forEach((v) => v.classList.toggle("active", v.id === `vue-${b.dataset.vue}`));
    const charger = { carte: () => carte && carte.invalidateSize(), zones: chargerZones, doublons: chargerDoublons, anomalies: chargerAnomalies, agents: chargerAgents };
    (charger[b.dataset.vue] || (() => {}))();
  })
);

/* ------------------------------------------------------------ tuiles */
async function chargerResume() {
  const r = await api("/api/resume");
  const zp = r.zones_par_statut || {};
  const dp = r.doublons_en_attente || {};
  const ap = r.anomalies_ouvertes || {};
  const nbDoublons = (dp.probable || 0) + (dp.a_verifier || 0);
  const nbAnomalies = (ap.haute || 0) + (ap.moyenne || 0) + (ap.basse || 0);
  const tuiles = [
    ["Population attendue", fmt(r.population_attendue), "estimation GRID3 / RGPH"],
    ["Personnes enregistrées", fmt(r.personnes_uniques), `${fmt(r.personnes)} fiches, ${fmt(r.personnes - r.personnes_uniques)} en double`],
    ["Couverture globale", pct(r.taux_global), `${fmt(r.menages)} ménages`],
    ["Zones en rouge", fmt(zp.rouge || 0), `sur ${fmt(r.zones)} zones · ${fmt(zp.orange || 0)} en orange`],
    ["Doublons à trancher", fmt(nbDoublons), `${fmt(dp.probable || 0)} probables`],
    ["Saisies suspectes", fmt(nbAnomalies), `${fmt(ap.haute || 0)} graves`],
  ];
  $("#tuiles").innerHTML = tuiles
    .map(([e, v, s]) => `<div class="tuile"><div class="etiquette">${esc(e)}</div><div class="valeur">${esc(v)}</div><div class="sous">${esc(s)}</div></div>`)
    .join("");
  $("#nb-doublons").textContent = nbDoublons || "";
  $("#nb-anomalies").textContent = ap.haute || "";
}

/* ------------------------------------------------------------ carte */
let carte = null;
let coucheZones = null;
const infobulle = $("#infobulle");

function placerInfobulle(e, html) {
  infobulle.innerHTML = html;
  infobulle.hidden = false;
  const x = e.originalEvent.clientX, y = e.originalEvent.clientY;
  const l = infobulle.offsetWidth, h = infobulle.offsetHeight;
  infobulle.style.left = `${Math.min(window.innerWidth - l - 8, x + 14)}px`;
  infobulle.style.top = `${Math.min(window.innerHeight - h - 8, y + 14)}px`;
}

function htmlZone(p) {
  return `<div class="t">${esc(p.nom)} <span class="aide">${esc(p.code)}</span></div>
    <div style="margin-bottom:6px">${statutHTML(p.statut)}</div>
    <div class="l">Population attendue <b>${fmt(p.population_estimee)}</b></div>
    <div class="l">Personnes enregistrées <b>${fmt(p.personnes_uniques)}</b></div>
    <div class="l">Couverture <b>${pct(p.taux)}</b></div>
    <div class="l">Manquants estimés <b>${fmt(p.manquants)}</b></div>
    <div class="l">Ménages <b>${fmt(p.menages)}</b></div>`;
}

function initialiserCarte() {
  carte = L.map("carte", { zoomControl: true, attributionControl: true }).setView([-4.38, 15.3], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; contributeurs OpenStreetMap",
  }).addTo(carte);
  $("#legende").innerHTML = ["vert", "orange", "rouge", "surcouverture", "sans_estimation"].map((s) => `<span>${statutHTML(s)}</span>`).join("");
}

async function chargerNiveaux() {
  const niveaux = await api("/api/niveaux");
  const sel = $("#filtre-niveau");
  if (!niveaux.length) {
    sel.innerHTML = `<option value="">—</option>`;
    return;
  }
  const parDefaut = niveaux.reduce((a, b) => (b.zones > a.zones ? b : a)).niveau;
  sel.innerHTML = niveaux.map((n) => `<option value="${esc(n.niveau)}" ${n.niveau === parDefaut ? "selected" : ""}>${esc(n.niveau)} (${n.zones})</option>`).join("");
}

async function chargerCarte() {
  const niveau = $("#filtre-niveau").value;
  const geo = await api(`/api/zones.geojson${niveau ? `?niveau=${encodeURIComponent(niveau)}` : ""}`);
  if (coucheZones) coucheZones.remove();
  coucheZones = L.geoJSON(geo, {
    style: (f) => ({ color: "#ffffff", weight: 2, fillColor: (STATUTS[f.properties.statut] || STATUTS.non_calcule).coul, fillOpacity: 0.62 }),
    onEachFeature: (f, couche) => {
      couche.on("mousemove", (e) => placerInfobulle(e, htmlZone(f.properties)));
      couche.on("mouseover", () => couche.setStyle({ weight: 3, color: "#12355b" }));
      couche.on("mouseout", () => { infobulle.hidden = true; coucheZones.resetStyle(couche); });
      couche.on("click", () => carte.fitBounds(couche.getBounds(), { maxZoom: 15 }));
      couche.feature.properties._couche = couche;
    },
  }).addTo(carte);
  if (geo.features.length) carte.fitBounds(coucheZones.getBounds(), { padding: [12, 12] });

  const prioritaires = geo.features
    .map((f) => f.properties)
    .filter((p) => p.statut === "rouge" || p.statut === "orange")
    .sort((a, b) => (b.manquants || 0) - (a.manquants || 0));
  $("#priorites").innerHTML = prioritaires.length
    ? prioritaires
        .map((p, i) => `<li data-i="${i}"><div class="ligne1"><span>${esc(p.nom)}</span>${statutHTML(p.statut)}</div>
          <div class="ligne2">${pct(p.taux)} couverts · environ ${fmt(p.manquants)} personnes à enregistrer</div></li>`)
        .join("")
    : `<li class="aide">Aucune zone en retard.</li>`;
  document.querySelectorAll("#priorites li[data-i]").forEach((li) =>
    li.addEventListener("click", () => {
      const p = prioritaires[Number(li.dataset.i)];
      if (p._couche) carte.fitBounds(p._couche.getBounds(), { maxZoom: 15 });
    })
  );
}
$("#filtre-niveau").addEventListener("change", () => { chargerCarte(); chargerZones(); });

/* ------------------------------------------------------------ tableau des zones */
let triZones = { cle: "taux", sens: 1 };
async function chargerZones() {
  const niveau = $("#filtre-niveau").value;
  const lignes = await api(`/api/couverture${niveau ? `?niveau=${encodeURIComponent(niveau)}` : ""}`);
  const cols = [
    ["code", "Code"], ["nom", "Zone"], ["population_estimee", "Attendus", true], ["personnes_uniques", "Enregistrés", true],
    ["taux", "Couverture", true], ["manquants", "Manquants", true], ["menages", "Ménages", true], ["statut", "Statut"],
  ];
  lignes.sort((a, b) => {
    const x = a[triZones.cle], y = b[triZones.cle];
    if (x === y) return 0;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return (x > y ? 1 : -1) * triZones.sens;
  });
  $("#table-zones").innerHTML =
    `<thead><tr>${cols.map(([c, l, n]) => `<th data-cle="${c}" class="${n ? "nombre" : ""}">${l}${triZones.cle === c ? (triZones.sens > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>` +
    `<tbody>${lignes
      .map((z) => {
        const coul = (STATUTS[z.statut] || STATUTS.non_calcule).coul;
        const largeur = Math.min(100, Math.round((z.taux || 0) * 100));
        return `<tr><td>${esc(z.code)}</td><td>${esc(z.nom)}</td><td class="nombre">${fmt(z.population_estimee)}</td>
          <td class="nombre">${fmt(z.personnes_uniques)}</td>
          <td class="nombre">${pct(z.taux)}<div class="jauge" aria-hidden="true"><div style="width:${largeur}%;background:${coul}"></div></div></td>
          <td class="nombre">${fmt(z.manquants)}</td><td class="nombre">${fmt(z.menages)}</td><td>${statutHTML(z.statut)}</td></tr>`;
      })
      .join("")}</tbody>`;
  document.querySelectorAll("#table-zones th").forEach((th) =>
    th.addEventListener("click", () => {
      triZones = { cle: th.dataset.cle, sens: triZones.cle === th.dataset.cle ? -triZones.sens : 1 };
      chargerZones();
    })
  );
}

/* ------------------------------------------------------------ doublons */
function ficheHTML(titre, p) {
  const naissance = p.date_naissance || (p.annee_naissance ? `vers ${p.annee_naissance}` : "—");
  return `<div class="fiche"><div class="titre">${esc(titre)} · ${p.nom ? esc(p.nom) : `<span title="Nom non conservé (protection des données) : clé phonétique affichée">${esc(p.cles || "—")} <span class=\"aide\">(clé phonétique)</span></span>`}</div><dl>
    <dt>Sexe</dt><dd>${esc(p.sexe || "—")}</dd>
    <dt>Naissance</dt><dd>${esc(naissance)}${p.age !== null && p.age !== undefined ? ` (${p.age} ans)` : ""}</dd>
    <dt>Lien</dt><dd>${esc(LIENS[p.lien] || p.lien || "—")}</dd>
    <dt>Ménage</dt><dd>${esc(p.menage)}</dd>
    <dt>Agent</dt><dd>${esc(p.agent_id || "—")}</dd>
    <dt>Zone</dt><dd>${esc(p.zone || "—")}</dd>
    <dt>Collecte</dt><dd>${esc(p.collecte_le ? p.collecte_le.slice(0, 16).replace("T", " ") : "—")}</dd></dl></div>`;
}

function criteresHTML(d) {
  const parts = [];
  const etiquettes = { nom: "Nom", naissance: "Naissance", lieu: "Lieu", lien: "Lien" };
  for (const [k, l] of Object.entries(etiquettes)) if (d[k] !== undefined) parts.push(`<span class="critere">${l} <b>${Math.round(d[k] * 100)} %</b></span>`);
  if (d.distance_m !== undefined) parts.push(`<span class="critere">Distance <b>${fmt(d.distance_m)} m</b></span>`);
  if (d.nin) parts.push(`<span class="critere">NIN <b>${esc(d.nin)}</b></span>`);
  if (d.menage_en_double) parts.push(`<span class="critere"><b>${d.menage_en_double}</b> membres du ménage en double</span>`);
  if (d.meme_menage) parts.push(`<span class="critere"><b>même ménage</b></span>`);
  if (d.nom_frequent) parts.push(`<span class="critere">nom porté par <b>${d.nom_frequent}</b> fiches</span>`);
  if (d.sexe) parts.push(`<span class="critere">sexe <b>${esc(d.sexe)}</b></span>`);
  return parts.join("");
}

async function chargerDoublons() {
  const niveau = $("#filtre-doublon-niveau").value;
  const statut = $("#filtre-doublon-statut").value;
  const r = await api(`/api/doublons?statut=${statut}${niveau ? `&niveau=${niveau}` : ""}&limite=100`);
  $("#info-doublons").textContent = `${fmt(r.total)} paires · triées par score`;
  const menages = await api("/api/doublons/menages");
  $("#menages-doubles").innerHTML = menages.length
    ? `<div class="encadre"><b>${menages.length} ménage(s) probablement visités deux fois</b> : ${menages
        .slice(0, 6)
        .map((m) => `${esc(m.menage_a)} (${esc(m.agent_a)}) et ${esc(m.menage_b)} (${esc(m.agent_b)}), ${m.personnes_communes} personnes`)
        .join(" ; ")}${menages.length > 6 ? "…" : ""}</div>`
    : "";
  $("#liste-doublons").innerHTML = r.paires.length
    ? r.paires
        .map((p) => `<article class="paire" data-id="${p.id}">
          <div class="haut"><span class="score">${Math.round(p.score * 100)} %</span>
            <span class="niveau ${esc(p.niveau)}">${p.niveau === "probable" ? "Doublon probable" : "À vérifier"}</span>
            <span class="aide">${p.statut !== "en_attente" ? `Décision : ${esc(p.statut)}${p.decide_par ? ` par ${esc(p.decide_par)}` : ""}` : ""}</span></div>
          <div class="fiches">${ficheHTML("Fiche A", p.a)}${ficheHTML("Fiche B", p.b)}</div>
          <div class="criteres">${criteresHTML(p.details)}</div>
          <div class="actions">
            <button class="btn oui" data-decision="confirme">C'est la même personne</button>
            <button class="btn" data-decision="rejete">Ce sont deux personnes différentes</button>
          </div></article>`)
        .join("")
    : `<div class="vide">Aucune paire dans cette sélection.</div>`;
  document.querySelectorAll(".paire .btn").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.closest(".paire").dataset.id;
      try {
        await api(`/api/doublons/${id}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: b.dataset.decision }) });
        await Promise.all([chargerDoublons(), chargerResume(), chargerCarte()]);
      } catch (err) {
        alert(`Décision non enregistrée : ${err.message}`);
      }
    })
  );
}
$("#filtre-doublon-niveau").addEventListener("change", chargerDoublons);
$("#filtre-doublon-statut").addEventListener("change", chargerDoublons);

/* ------------------------------------------------------------ anomalies */
async function chargerAnomalies() {
  const gravite = $("#filtre-gravite").value;
  const statut = $("#filtre-anomalie-statut").value;
  const r = await api(`/api/anomalies?statut=${statut}${gravite ? `&gravite=${gravite}` : ""}&limite=500`);
  $("#table-anomalies").innerHTML = r.anomalies.length
    ? `<thead><tr><th>Gravité</th><th>Contrôle</th><th>Détail</th><th>Agent</th><th>Ménage</th><th>Statut</th><th></th></tr></thead><tbody>${r.anomalies
        .map((a) => `<tr data-id="${a.id}"><td><span class="gravite ${esc(a.gravite)}">${esc(a.gravite)}</span></td><td>${esc(a.libelle)}</td>
          <td>${esc(a.detail || "—")}</td><td>${esc(a.agent_id || "—")}</td><td>${esc(a.menage || "—")}</td><td>${esc(a.statut)}</td>
          <td><button class="btn" data-statut="justifiee">Justifiée</button> <button class="btn" data-statut="corrigee">Corrigée</button></td></tr>`)
        .join("")}</tbody>`
    : `<tbody><tr><td class="vide">Aucune saisie suspecte dans cette sélection.</td></tr></tbody>`;
  document.querySelectorAll("#table-anomalies .btn").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.closest("tr").dataset.id;
      try {
        await api(`/api/anomalies/${id}/statut`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ statut: b.dataset.statut }) });
        await Promise.all([chargerAnomalies(), chargerResume()]);
      } catch (err) {
        alert(`Statut non enregistré : ${err.message}`);
      }
    })
  );
}
$("#filtre-gravite").addEventListener("change", chargerAnomalies);
$("#filtre-anomalie-statut").addEventListener("change", chargerAnomalies);

/* ------------------------------------------------------------ agents */
async function chargerAgents() {
  const lignes = await api("/api/agents");
  $("#table-agents").innerHTML = `<thead><tr><th>Agent</th><th class="nombre">Ménages</th><th class="nombre">Personnes</th>
    <th class="nombre">Anomalies graves</th><th class="nombre">Anomalies</th><th class="nombre">Anomalies par ménage</th><th class="nombre">Doublons</th></tr></thead>
    <tbody>${lignes
      .map((a) => `<tr><td>${esc(a.agent_id)}</td><td class="nombre">${fmt(a.menages)}</td><td class="nombre">${fmt(a.personnes)}</td>
        <td class="nombre">${fmt(a.anomalies_hautes)}</td><td class="nombre">${fmt(a.anomalies)}</td>
        <td class="nombre">${a.taux_anomalies === null ? "—" : a.taux_anomalies.toFixed(2).replace(".", ",")}</td><td class="nombre">${fmt(a.doublons)}</td></tr>`)
      .join("")}</tbody>`;
}

/* ------------------------------------------------------------ import */
$("#cle-api").value = sessionStorage.getItem("decensio-cle") || "";
$("#utilisateur").value = sessionStorage.getItem("decensio-utilisateur") || "";
$("#cle-api").addEventListener("change", (e) => sessionStorage.setItem("decensio-cle", e.target.value));
$("#utilisateur").addEventListener("change", (e) => sessionStorage.setItem("decensio-utilisateur", e.target.value));

function brancherFormulaire(id, url) {
  $(id).addEventListener("submit", async (e) => {
    e.preventDefault();
    const sortie = $("#resultat-import");
    sortie.textContent = "Import en cours…";
    try {
      const r = await api(url, { method: "POST", body: new FormData(e.target) });
      sortie.textContent = JSON.stringify(r, null, 2);
      await toutRecharger();
    } catch (err) {
      sortie.textContent = `Échec : ${err.message}`;
    }
  });
}
brancherFormulaire("#form-enregistrements", "/api/import/enregistrements");
brancherFormulaire("#form-zones", "/api/import/zones");
brancherFormulaire("#form-estimations", "/api/import/estimations");
$("#btn-recalcul").addEventListener("click", async () => {
  const sortie = $("#resultat-import");
  sortie.textContent = "Calcul en cours…";
  try {
    sortie.textContent = JSON.stringify(await api("/api/recalcul", { method: "POST" }), null, 2);
    await toutRecharger();
  } catch (err) {
    sortie.textContent = `Échec : ${err.message}`;
  }
});

/* ------------------------------------------------------------ démarrage */
async function toutRecharger() {
  await chargerResume();
  await chargerNiveaux();
  await chargerCarte();
}

if (CONFIG.statique) {
  document.body.classList.add("demo");
  $("#bandeau-demo").hidden = false;
  document.querySelector('.onglet[data-vue="import"]').hidden = true;
} else if (CONFIG.api) {
  // Toujours montrer à quel serveur la page parle : la clé d'API n'est envoyée qu'à lui.
  const bandeau = $("#bandeau-demo");
  bandeau.textContent = `Connecté au serveur Decensio : ${CONFIG.api}`;
  bandeau.hidden = false;
}
initialiserCarte();
toutRecharger().catch((err) => {
  $("#tuiles").innerHTML = `<div class="vide">Impossible de joindre l'API : ${esc(err.message)}</div>`;
});

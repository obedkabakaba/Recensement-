/* Configuration du tableau de bord.
 *
 * statique : true  -> démonstration sans serveur : lit les fichiers JSON du dossier « donnees/ »
 *                     (données fictives, consultation seule). C'est le mode de GitHub Pages.
 * api      : adresse du serveur Decensio (dépôt privé Recensement-backend) quand statique vaut false.
 *
 * Pour essayer avec un serveur sans modifier ce fichier : ajouter ?api=http://127.0.0.1:8000 à l'adresse.
 */
window.DECENSIO = { api: "", statique: true };

(function () {
  const api = new URLSearchParams(window.location.search).get("api");
  if (api) window.DECENSIO = { api: api.replace(/\/+$/, ""), statique: false };
})();

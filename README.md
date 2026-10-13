# 🏥 HepaVol — Plateforme Web Moderne de Volumétrie Hépatique par IA

Application complète permettant de réaliser des **volumétries hépatiques automatiques à partir d'examens scanner (DICOM)** en exploitant l'intelligence artificielle de **TotalSegmentator** et le moteur médical **3D Slicer**, dotée d'une **interface web moderne** et d'un **lanceur macOS `.command` en un clic**.

---

## 🚀 Démarrage Rapide

### Méthode 1 : Double-clic (Recommandé sur macOS)
Double-cliquez simplement sur le fichier :
```
Lancer_Volumetrie.command
```
Ce script :
1. Vérifie votre environnement Python et installe les modules requis si nécessaire.
2. Détecte automatiquement l'installation de **3D Slicer** (`/Applications/Slicer.app`).
3. Démarre le serveur local sécurisé.
4. Ouvre automatiquement votre navigateur par défaut à l'adresse **`http://localhost:8000`**.

> 💡 *Note macOS :* Si macOS affiche un avertissement de sécurité lors du tout premier lancement, faites un **Clic droit (ou Contrôle + Clic)** sur `Lancer_Volumetrie.command` puis cliquez sur **Ouvrir**.

---

### Méthode 2 : En ligne de commande
Dans un terminal :
```bash
cd /Volumes/AL_SSDext/Antigravity-projects/Volumetrie
python3 app.py
```
Puis ouvrez votre navigateur sur [http://localhost:8000](http://localhost:8000).

---

## ✨ Fonctionnalités Principales

### 1. Sélection Facile des Séries DICOM
- **Bouton « 📁 Parcourir sur Mac... »** : Ouvre directement le sélecteur natif du Finder macOS (permet de choisir n'importe quel dossier sur votre disque interne ou disque externe `/Volumes/...`).
- **Glisser-Déposer** de dossiers DICOM.
- Saisie manuelle de chemin avec validation instantanée du nombre de coupes.

### 2. Options de Segmentation IA (TotalSegmentator)
- **🎯 Pleine Résolution (~1.5 mm)** : Segmentation anatomique ultra-précise (recommandée pour la planification chirurgicale et les hépatectomies).
- **⚡ Mode Rapide (~3 mm)** : Prévisualisation volumétrique en ~1 à 2 minutes (`fast=True`).
- **Organes ciblés** :
  - **Foie** (*Liver*) en cible principale.
  - **Rate** (*Spleen*) optionnelle pour le calcul de l'index hépato-splénique et le dépistage de l'hypertension portale.

### 3. Calculs Biométriques & Cliniques Avancés
- **Volume Hépatique Total mesuré** en **$cm^3$ (mL)** et en **Litres**.
- **Volume Théorique Standard (Formule de Vauthey & Urata)** :
  - Calcul de la surface corporelle ($BSA$ en $m^2$, formule de Mosteller) si la taille et le poids sont renseignés.
  - Calcul du ratio volume mesuré / volume théorique attendu (évaluation d'hépatomégalie ou atrophie).
- **Atténuation tissulaire moyenne (Unités Hounsfield - HU)** :
  - Évaluation de la stéatose hépatique (densité normale : 50 à 65 HU, stéatose suspectée si $< 40$ HU).
- **Ratio Hépato-Splénique** : volume du foie / volume de la rate.

### 4. Visualiseur 3D Interactif Autonome (WebGL / STL)
- Rendu 3D temps réel du foie reconstruit dans le navigateur.
- **100% Hors-Ligne** : Aucun chargement de CDN externe n'est requis, fonctionne en réseau hospitalier isolé.
- Contrôles : rotation 360°, zoom molette, translation, mode plein / fil de fer, palettes de couleurs (foie, ambre, cyan médical, vert émeraude), capture d'écran 3D en 1 clic.

### 5. Contrôle Visuel 2D (Coupes Scanner Axiales)
- Génération automatique de coupes axiales scanner avec fenêtrage abdominal standard ($W:400, L:40$ HU) et superposition couleur semi-transparente du contour hépatique (coupes supérieure, médiane, inférieure).

### 6. Exportations & Compte-Rendu Médical
- **Compte-Rendu Clinique A4** : Prêt à imprimer ou à exporter en PDF via le navigateur, avec identification du patient, paramètres de l'acquisition scanner, synthèse volumétrique, coupes scanner et zone de signature.
- **Export Maillage 3D (.STL)** : Pour impression 3D ou importation dans des logiciels de chirurgie / CAO (Blender, Mimics, etc.).
- **Export Données Brutes (.JSON)** : Pour archivage ou intégration dans des études de recherche.

---

## 📁 Structure du Projet

```
Volumetrie/
├── Lancer_Volumetrie.command    # 🚀 Lanceur macOS double-cliquable
├── app.py                       # 🌐 Serveur Web FastAPI et gestionnaire de tâches
├── slicer_worker.py             # 🧠 Moteur d'analyse exécuté au sein de 3D Slicer
├── requirements.txt             # 📦 Dépendances Python (FastAPI, Uvicorn, Pillow...)
├── static/
│   ├── css/
│   │   └── style.css            # 🎨 Feuille de style moderne (Dark Medical UI)
│   └── js/
│       ├── app.js               # ⚡ Logique client, streaming SSE, formulaires
│       └── stl_viewer.js        # 🪐 Visualiseur 3D WebGL médical autonome (zéro dépendance)
├── templates/
│   ├── index.html               # 🖥️ Interface principale du tableau de bord
│   └── report.html              # 📄 Modèle de compte-rendu médical A4 (PDF)
├── output/                      # 💾 Dossier contenant l'historique et résultats des analyses
└── README.md                    # 📖 Documentation complète
```

---

## 🩺 Formules Médicales Utilisées

### 1. Formule de Vauthey et al. (*Am J Surg 2002*)
$$\text{TLV} = -794.41 + 1267.28 \times \text{BSA} \quad (\text{cm}^3)$$
avec la surface corporelle (Mosteller) :
$$\text{BSA} = \sqrt{\frac{\text{Taille (cm)} \times \text{Poids (kg)}}{3600}} \quad (\text{m}^2)$$

### 2. Formule de Urata et al. (*Hepatology 1995*)
$$\text{TLV} = 706.2 \times \text{BSA} + 2.4 \quad (\text{cm}^3)$$

### 3. Évaluation de l'Atténuation (Stéatose Hépatique)
- Densité normale : $50 \text{ à } 65 \text{ HU}$ (sur scanner sans injection).
- Stéatose hépatique probable : Atténuation moyenne parenchymateuse $< 40 \text{ HU}$.

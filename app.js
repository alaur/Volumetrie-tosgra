/**
 * app.js
 * Logique Frontend pour HepaVol (Volumétrie Hépatique IA)
 */

document.addEventListener('DOMContentLoaded', () => {
    // Éléments du DOM
    const navTabs = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const slicerStatusBadge = document.getElementById('slicerStatusBadge');
    
    // Formulaire d'analyse
    const analysisForm = document.getElementById('analysisForm');
    const inputPathInput = document.getElementById('inputPath');
    const btnPickFolder = document.getElementById('btnPickFolder');
    const pathFeedback = document.getElementById('pathFeedback');
    const dropzone = document.getElementById('dropzone');

    const arterialPathInput = document.getElementById('arterialPath');
    const btnPickArterialFolder = document.getElementById('btnPickArterialFolder');
    const arterialPathFeedback = document.getElementById('arterialPathFeedback');
    const dropzoneArterial = document.getElementById('dropzoneArterial');

    const btnStartAnalysis = document.getElementById('btnStartAnalysis');
    
    // Panneau de progression
    const executionPanel = document.getElementById('executionPanel');
    const progressBarFill = document.getElementById('progressBarFill');
    const progressPercent = document.getElementById('progressPercent');
    const progressStep = document.getElementById('progressStep');
    const terminalLogs = document.getElementById('terminalLogs');
    const btnCancelJob = document.getElementById('btnCancelJob');

    // Résultats
    const resultsTabBtn = document.querySelector('[data-tab="results"]');
    const kpiLiverVol = document.getElementById('kpiLiverVol');
    const kpiLiverVolLiters = document.getElementById('kpiLiverVolLiters');
    const kpiLiverDensity = document.getElementById('kpiLiverDensity');
    const kpiSteatosisBadge = document.getElementById('kpiSteatosisBadge');
    const kpiTheoVol = document.getElementById('kpiTheoVol');
    const kpiTheoRatio = document.getElementById('kpiTheoRatio');
    const kpiSpleenCard = document.getElementById('kpiSpleenCard');
    const kpiSpleenVol = document.getElementById('kpiSpleenVol');
    const kpiHsRatio = document.getElementById('kpiHsRatio');

    const patientDetailsTable = document.getElementById('patientDetailsTable');
    const acquisitionDetailsTable = document.getElementById('acquisitionDetailsTable');
    const sliceGallery = document.getElementById('sliceGallery');
    const btnDownloadStl = document.getElementById('btnDownloadStl');
    const btnDownloadJson = document.getElementById('btnDownloadJson');
    const btnOpenReport = document.getElementById('btnOpenReport');
    const btnGoToMpr = document.getElementById('btnGoToMpr');
    const btnOpenMprNewWindow = document.getElementById('btnOpenMprNewWindow');
    const btnMprOpenStandalone = document.getElementById('btnMprOpenStandalone');

    // Bilan de Lille & Simulateur Biométrique
    const lilleSection = document.getElementById('lilleSection');
    const lillePatientWeightDisp = document.getElementById('lillePatientWeightDisp');
    const lilleTotalBwPct = document.getElementById('lilleTotalBwPct');
    const lilleRightBwPct = document.getElementById('lilleRightBwPct');
    const badgeRightSafety = document.getElementById('badgeRightSafety');
    const lilleLeftBwPct = document.getElementById('lilleLeftBwPct');
    const badgeLeftSafety = document.getElementById('badgeLeftSafety');
    const lilleLeftLatBwPct = document.getElementById('lilleLeftLatBwPct');
    const badgeLeftLatSafety = document.getElementById('badgeLeftLatSafety');
    const quickWeight = document.getElementById('quickWeight');
    const quickHeight = document.getElementById('quickHeight');
    const quickSpleenVol = document.getElementById('quickSpleenVol');
    const btnUpdateBiometrics = document.getElementById('btnUpdateBiometrics');

    // Stéatose & Balance Hépato-Splénique
    const parenchymaSection = document.getElementById('parenchymaSection');
    const steatStatus = document.getElementById('steatStatus');
    const steatGradeBadge = document.getElementById('steatGradeBadge');
    const steatLiverHu = document.getElementById('steatLiverHu');
    const steatInfiltration = document.getElementById('steatInfiltration');
    const steatSpleenHu = document.getElementById('steatSpleenHu');
    const steatDiffHu = document.getElementById('steatDiffHu');
    const steatNoteText = document.getElementById('steatNoteText');
    const hsRatioVal = document.getElementById('hsRatioVal');
    const hsRatioBadge = document.getElementById('hsRatioBadge');
    const hsLiverVolDisp = document.getElementById('hsLiverVolDisp');
    const hsSpleenVolDisp = document.getElementById('hsSpleenVolDisp');
    const hsInterpretationText = document.getElementById('hsInterpretationText');

    // Historique
    const historyTableBody = document.getElementById('historyTableBody');

    // État local
    let currentJobId = null;
    let eventSource = null;
    let stlViewerInstance = null;

    // --- Navigation par Onglets ---
    navTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            navTabs.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetContent = document.getElementById(`tab-${targetTab}`);
            if (targetContent) targetContent.classList.add('active');

            if (targetTab === 'results' && stlViewerInstance) {
                setTimeout(() => stlViewerInstance.resize(), 100);
            }
            if (targetTab === 'mpr' && currentJobId) {
                const mprIframe = document.getElementById('mprIframe');
                if (mprIframe && (!mprIframe.src || mprIframe.src === 'about:blank' || !mprIframe.src.includes(currentJobId))) {
                    mprIframe.src = `/mpr-viewer/${currentJobId}`;
                }
            }
            if (targetTab === 'history') {
                loadHistory();
            }
        });
    });

    // --- Diagnostic Système initial ---
    checkSystemStatus();

    async function checkSystemStatus() {
        try {
            const res = await fetch('/api/system-status');
            const data = await res.json();
            if (data.slicer_installed) {
                slicerStatusBadge.className = 'status-badge online';
                slicerStatusBadge.innerHTML = `<span class="pulse-dot"></span> Slicer Connecté`;
                document.getElementById('sysSlicerPath').textContent = data.slicer_path;
            } else {
                slicerStatusBadge.className = 'status-badge offline';
                slicerStatusBadge.innerHTML = `<span class="pulse-dot"></span> Slicer Non Détecté`;
                document.getElementById('sysSlicerPath').textContent = "Introuvable (/Applications/Slicer.app)";
            }
            document.getElementById('sysPythonVer').textContent = `Python ${data.python_version}`;
        } catch (err) {
            console.error("Erreur vérification système :", err);
        }
    }

    // --- Sélection Native de Dossier sur Mac ---
    // --- Sélection Native de Dossier sur Mac (Phase Portale & Phase Artérielle) ---
    btnPickFolder.addEventListener('click', async () => {
        btnPickFolder.disabled = true;
        btnPickFolder.innerHTML = `⏳ Sélection...`;
        try {
            const res = await fetch('/api/pick-folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: "Sélectionnez le dossier contenant les images DICOM de la Phase Portale (Requis)" })
            });
            const data = await res.json();
            if (data.success && data.path) {
                inputPathInput.value = data.path;
                validatePath(data.path, pathFeedback);
            }
        } catch (e) {
            console.error("Erreur choix dossier portale :", e);
        } finally {
            btnPickFolder.disabled = false;
            btnPickFolder.innerHTML = `📁 Parcourir...`;
        }
    });

    if (btnPickArterialFolder) {
        btnPickArterialFolder.addEventListener('click', async () => {
            btnPickArterialFolder.disabled = true;
            btnPickArterialFolder.innerHTML = `⏳ Sélection...`;
            try {
                const res = await fetch('/api/pick-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: "Sélectionnez le dossier contenant les images DICOM de la Phase Artérielle (Optionnel pour MPR/MIP)" })
                });
                const data = await res.json();
                if (data.success && data.path) {
                    arterialPathInput.value = data.path;
                    validatePath(data.path, arterialPathFeedback);
                }
            } catch (e) {
                console.error("Erreur choix dossier artériel :", e);
            } finally {
                btnPickArterialFolder.disabled = false;
                btnPickArterialFolder.innerHTML = `📁 Parcourir...`;
            }
        });
    }

    // Validation manuelle de chemin
    inputPathInput.addEventListener('change', () => {
        if (inputPathInput.value.trim()) validatePath(inputPathInput.value.trim(), pathFeedback);
    });
    inputPathInput.addEventListener('input', () => {
        let val = inputPathInput.value.trim();
        if (val.startsWith('file://')) {
            val = decodeURIComponent(val.replace(/^file:\/\//, ''));
            inputPathInput.value = val;
        }
        if (val) validatePath(val, pathFeedback);
    });
    inputPathInput.addEventListener('drop', (e) => {
        setTimeout(() => {
            let val = inputPathInput.value.trim();
            if (val.startsWith('file://')) {
                val = decodeURIComponent(val.replace(/^file:\/\//, ''));
                inputPathInput.value = val;
            }
            if (val) validatePath(val, pathFeedback);
        }, 50);
    });

    if (arterialPathInput) {
        arterialPathInput.addEventListener('change', () => {
            if (arterialPathInput.value.trim()) validatePath(arterialPathInput.value.trim(), arterialPathFeedback);
        });
        arterialPathInput.addEventListener('input', () => {
            let val = arterialPathInput.value.trim();
            if (val.startsWith('file://')) {
                val = decodeURIComponent(val.replace(/^file:\/\//, ''));
                arterialPathInput.value = val;
            }
            if (val) validatePath(val, arterialPathFeedback);
        });
        arterialPathInput.addEventListener('drop', (e) => {
            setTimeout(() => {
                let val = arterialPathInput.value.trim();
                if (val.startsWith('file://')) {
                    val = decodeURIComponent(val.replace(/^file:\/\//, ''));
                    arterialPathInput.value = val;
                }
                if (val) validatePath(val, arterialPathFeedback);
            }, 50);
        });
    }

    async function validatePath(path, targetFeedback = pathFeedback) {
        if (!targetFeedback) return;
        targetFeedback.innerHTML = `<span style="color: var(--text-dim);">Vérification du chemin...</span>`;
        try {
            const res = await fetch('/api/validate-path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path })
            });
            const data = await res.json();
            if (data.valid) {
                targetFeedback.innerHTML = `<span class="text-success">✓ ${data.message}</span>`;
            } else {
                targetFeedback.innerHTML = `<span class="text-danger">✗ ${data.message}</span>`;
            }
        } catch (e) {
            targetFeedback.innerHTML = ``;
        }
    }

    // Récupération récursive de tous les fichiers à partir de l'objet DataTransfer
    async function getAllFilesFromDataTransfer(dataTransfer) {
        const files = [];
        const items = dataTransfer.items;
        
        if (items && items.length > 0 && items[0].webkitGetAsEntry) {
            const queue = [];
            for (let i = 0; i < items.length; i++) {
                const entry = items[i].webkitGetAsEntry();
                if (entry) queue.push(entry);
            }

            while (queue.length > 0) {
                const entry = queue.shift();
                if (entry.isFile) {
                    const file = await new Promise(resolve => entry.file(resolve, () => resolve(null)));
                    if (file && !file.name.startsWith('.') && file.name !== 'Icon\r') {
                        files.push(file);
                    }
                } else if (entry.isDirectory) {
                    const dirReader = entry.createReader();
                    const entries = await new Promise(resolve => {
                        const result = [];
                        function readBatch() {
                            dirReader.readEntries(batch => {
                                if (!batch || batch.length === 0) {
                                    resolve(result);
                                } else {
                                    result.push(...batch);
                                    readBatch();
                                }
                            }, () => resolve(result));
                        }
                        readBatch();
                    });
                    for (const subEntry of entries) {
                        queue.push(subEntry);
                    }
                }
            }
        } else if (dataTransfer.files && dataTransfer.files.length > 0) {
            for (let i = 0; i < dataTransfer.files.length; i++) {
                const file = dataTransfer.files[i];
                if (!file.name.startsWith('.')) {
                    files.push(file);
                }
            }
        }
        return files;
    }

    // Gestionnaire générique de zone de glisser-déposer
    function setupGenericDropzone(dzEl, inputEl, feedbackEl, iconId, titleId, subId, defaultTitle, pickBtn) {
        if (!dzEl) return;

        function resetUI() {
            dzEl.classList.remove('dragover', 'loading');
            const iconEl = document.getElementById(iconId);
            const titleEl = document.getElementById(titleId);
            const subEl = document.getElementById(subId);
            if (iconEl) {
                iconEl.className = 'dropzone-icon';
                iconEl.textContent = '📥';
            }
            if (titleEl) titleEl.textContent = defaultTitle;
            if (subEl) subEl.innerHTML = 'ou cliquez pour parcourir dans le Finder';
        }

        dzEl.addEventListener('dragover', (e) => {
            e.preventDefault();
            dzEl.classList.add('dragover');
        });

        dzEl.addEventListener('dragleave', () => {
            dzEl.classList.remove('dragover');
        });

        dzEl.addEventListener('drop', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            dzEl.classList.remove('dragover');

            if (dzEl.classList.contains('loading')) return;

            let droppedText = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain') || '';
            if (droppedText) {
                let clean = droppedText.trim();
                if (clean.startsWith('file://')) {
                    clean = decodeURIComponent(clean.replace(/^file:\/\//, ''));
                }
                if (clean.startsWith('/') && !clean.includes('\n')) {
                    inputEl.value = clean;
                    await validatePath(clean, feedbackEl);
                    return;
                }
            }

            let topName = '';
            if (e.dataTransfer.items && e.dataTransfer.items.length > 0 && e.dataTransfer.items[0].webkitGetAsEntry) {
                const entry = e.dataTransfer.items[0].webkitGetAsEntry();
                if (entry) topName = entry.name;
            } else if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                topName = e.dataTransfer.files[0].name;
            }

            const iconEl = document.getElementById(iconId);
            const titleEl = document.getElementById(titleId);
            const subEl = document.getElementById(subId);

            if (topName) {
                dzEl.classList.add('loading');
                if (iconEl) {
                    iconEl.className = 'dropzone-icon dropzone-pulse';
                    iconEl.textContent = '🔍';
                }
                if (titleEl) titleEl.textContent = `Localisation de "${topName}" sur votre Mac...`;
                if (subEl) subEl.textContent = 'Vérification des dossiers...';

                try {
                    const locRes = await fetch('/api/locate-folder', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: topName })
                    });
                    const locData = await locRes.json();
                    if (locData.found && locData.path) {
                        inputEl.value = locData.path;
                        resetUI();
                        await validatePath(locData.path, feedbackEl);
                        return;
                    }
                } catch (locErr) {
                    console.warn("Recherche locale non disponible :", locErr);
                }
            }

            dzEl.classList.add('loading');
            if (iconEl) {
                iconEl.className = 'dropzone-icon dropzone-pulse';
                iconEl.textContent = '⏳';
            }
            if (titleEl) titleEl.textContent = 'Lecture du dossier déposé...';
            if (subEl) subEl.textContent = 'Analyse des coupes DICOM...';

            try {
                const files = await getAllFilesFromDataTransfer(e.dataTransfer);
                if (files.length === 0) {
                    resetUI();
                    alert("Aucun fichier lisible détecté.");
                    return;
                }

                if (subEl) subEl.textContent = `Importation rapide de ${files.length} fichier(s)...`;
                const formData = new FormData();
                const safeFolderName = topName ? topName.replace(/[^a-zA-Z0-9_\-\.]/g, '_') : 'dicom_upload';
                formData.append('folder_name', safeFolderName);
                for (const file of files) {
                    formData.append('files', file);
                }

                const uploadRes = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const uploadData = await uploadRes.json();
                resetUI();

                if (uploadData.success && uploadData.path) {
                    inputEl.value = uploadData.path;
                    await validatePath(uploadData.path, feedbackEl);
                } else {
                    alert(uploadData.error || "Impossible d'importer les fichiers déposés.");
                }
            } catch (dropErr) {
                console.error("Erreur glisser-déposer :", dropErr);
                resetUI();
                alert("Erreur lors du traitement du glisser-déposer : " + dropErr.message);
            }
        });

        dzEl.addEventListener('click', () => {
            if (!dzEl.classList.contains('loading') && pickBtn) {
                pickBtn.click();
            }
        });
    }

    setupGenericDropzone(dropzone, inputPathInput, pathFeedback, 'dropzoneIcon', 'dropzoneTitle', 'dropzoneSubtitle', 'Glissez le dossier Phase Portale ici', btnPickFolder);
    setupGenericDropzone(dropzoneArterial, arterialPathInput, arterialPathFeedback, 'dropzoneArterialIcon', 'dropzoneArterialTitle', 'dropzoneArterialSubtitle', 'Glissez le dossier Phase Artérielle ici', btnPickArterialFolder);

    // --- Lancement de l'Analyse ---
    analysisForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const inputPath = inputPathInput.value.trim();
        if (!inputPath) {
            alert("Veuillez sélectionner ou saisir le chemin du dossier DICOM.");
            return;
        }

        const useFast = document.getElementById('modeFast').checked;
        const targetOrgans = ["liver"];
        if (document.getElementById('organSpleen')?.checked) {
            targetOrgans.push("spleen");
        }
        const reconstructVessels = document.getElementById('organVessels')?.checked || false;
        if (reconstructVessels) {
            targetOrgans.push("vessels");
        }

        const weight = parseFloat(document.getElementById('patientWeight').value) || null;
        const height = parseFloat(document.getElementById('patientHeight').value) || null;
        const sex = document.getElementById('patientSex').value || "M";

        btnStartAnalysis.disabled = true;
        btnStartAnalysis.innerHTML = `⏳ Démarrage...`;

        // Affichage panneau d'exécution
        executionPanel.style.display = 'block';
        terminalLogs.innerHTML = '';
        progressBarFill.style.width = '0%';
        progressPercent.textContent = '0%';
        progressStep.textContent = 'Initialisation...';

        try {
            const segTaskEl = document.querySelector('input[name="segTask"]:checked');
            const segmentationTask = segTaskEl ? segTaskEl.value : "liver_segments";

            const arterialPath = arterialPathInput ? arterialPathInput.value.trim() : null;

            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input_path: inputPath,
                    portal_path: inputPath,
                    arterial_path: arterialPath || null,
                    use_fast: useFast,
                    target_organs: targetOrgans,
                    segmentation_task: segmentationTask,
                    reconstruct_vessels: reconstructVessels,
                    patient_weight: weight,
                    patient_height: height,
                    patient_sex: sex
                })
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Échec du lancement");
            }

            const data = await res.json();
            currentJobId = data.job_id;

            // Démarrage du flux SSE pour les logs
            startLogStream(currentJobId);

        } catch (err) {
            alert(`Erreur : ${err.message}`);
            btnStartAnalysis.disabled = false;
            btnStartAnalysis.innerHTML = `⚡ Démarrer la Volumétrie`;
        }
    });

    // --- Streaming SSE des Logs & Progression ---
    function startLogStream(jobId) {
        if (eventSource) eventSource.close();

        eventSource = new EventSource(`/api/stream/${jobId}`);

        eventSource.onmessage = (event) => {
            const msg = JSON.parse(event.data);

            // Progression
            if (msg.progress !== undefined) {
                progressBarFill.style.width = `${msg.progress}%`;
                progressPercent.textContent = `${msg.progress}%`;
            }
            if (msg.step) {
                progressStep.textContent = msg.step;
            }

            // Nouveaux logs
            if (msg.new_logs && msg.new_logs.length > 0) {
                msg.new_logs.forEach(line => {
                    const p = document.createElement('div');
                    p.className = 'terminal-line';
                    if (line.includes('[PROGRESS')) p.classList.add('progress');
                    else if (line.includes('[INFO]')) p.classList.add('info');
                    else if (line.includes('[ERROR]')) p.classList.add('error');
                    p.textContent = line;
                    terminalLogs.appendChild(p);
                });
                terminalLogs.scrollTop = terminalLogs.scrollHeight;
            }

            // Fin de traitement
            if (msg.status === 'completed') {
                eventSource.close();
                btnStartAnalysis.disabled = false;
                btnStartAnalysis.innerHTML = `⚡ Démarrer la Volumétrie`;
                fetchAndDisplayResults(jobId);
            } else if (msg.status === 'error') {
                eventSource.close();
                // Double vérification au cas où le fichier result.json est déjà écrit sur le disque
                fetch(`/api/job/${jobId}`)
                    .then(res => res.json())
                    .then(jobData => {
                        btnStartAnalysis.disabled = false;
                        btnStartAnalysis.innerHTML = `⚡ Démarrer la Volumétrie`;
                        if (jobData.status === 'completed') {
                            fetchAndDisplayResults(jobId);
                        } else {
                            progressStep.textContent = `Échec de l'analyse : ${jobData.error || msg.error || 'Erreur interne'}`;
                        }
                    })
                    .catch(() => {
                        btnStartAnalysis.disabled = false;
                        btnStartAnalysis.innerHTML = `⚡ Démarrer la Volumétrie`;
                        progressStep.textContent = `Échec de l'analyse : ${msg.error || 'Erreur interne'}`;
                    });
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
        };
    }

    // Interruption du travail
    btnCancelJob.addEventListener('click', async () => {
        if (!currentJobId) return;
        if (!confirm("Voulez-vous vraiment interrompre l'analyse en cours ?")) return;

        try {
            await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
            if (eventSource) eventSource.close();
            btnStartAnalysis.disabled = false;
            btnStartAnalysis.innerHTML = `⚡ Démarrer la Volumétrie`;
            progressStep.textContent = "Analyse interrompue.";
        } catch (e) {
            console.error(e);
        }
    });

    // --- Affichage des Résultats & Visualisation 3D ---
    async function fetchAndDisplayResults(jobId) {
        currentJobId = jobId;
        try {
            const res = await fetch(`/api/job/${jobId}`);
            const data = await res.json();
            const result = data.result;

            if (!result || result.status !== 'success') {
                alert("Résultats incomplets ou erreur lors du traitement.");
                return;
            }

            // 1. KPI Cards
            const liver = result.liver || {};
            kpiLiverVol.textContent = liver.volume_cm3 ? liver.volume_cm3.toLocaleString('fr-FR') : '--';
            kpiLiverVolLiters.textContent = liver.volume_liters ? `${liver.volume_liters} L` : '';

            // Densité & Stéatose
            if (liver.mean_hu !== null && liver.mean_hu !== undefined) {
                kpiLiverDensity.textContent = `${liver.mean_hu} HU`;
                const steat = result.steatosis_evaluation;
                if (steat) {
                    kpiSteatosisBadge.style.display = 'inline-block';
                    kpiSteatosisBadge.className = `badge ${steat.warning ? 'badge-warning' : 'badge-success'}`;
                    kpiSteatosisBadge.textContent = steat.status;
                }
            } else {
                kpiLiverDensity.textContent = '--';
                kpiSteatosisBadge.style.display = 'none';
            }

            // Volume Théorique (Vauthey), Critères de Lille, Stéatose & Ratio Hépato-Splénique
            try {
                updateBiometricsDisplay(result.theoretical_volume, result.lille_criteria || (liver && liver.lille_criteria), liver, result.patient_info || {}, result.steatosis_evaluation, result.hepato_splenic_ratio, result.spleen, result);
            } catch (errBio) {
                console.error("Erreur updateBiometricsDisplay :", errBio);
            }

            // Rate (si sélectionnée)
            const spleen = result.spleen;
            if (spleen && spleen.volume_cm3) {
                kpiSpleenCard.style.display = 'block';
                kpiSpleenVol.textContent = `${spleen.volume_cm3.toLocaleString('fr-FR')} cm³`;
                const hs = result.hepato_splenic_ratio;
                kpiHsRatio.textContent = hs ? `Ratio Foie/Rate : ${hs.ratio}` : '';
            } else {
                kpiSpleenCard.style.display = 'none';
            }

            // 2. Volumétrie des Segments de Couinaud (si disponible)
            const couinaudSec = document.getElementById('couinaudSection');
            const couinaudTbody = document.getElementById('couinaudTableBody');
            const couinaudSegments = result.couinaud_segments || (liver && liver.couinaud_segments);

            if (couinaudSegments && Object.keys(couinaudSegments).length > 0) {
                if (couinaudSec) couinaudSec.style.display = 'block';
                
                // Sous-totaux sectoriels
                if (liver.right_liver_volume_cm3 !== undefined) {
                    const rEl = document.getElementById('rightLiverVol');
                    const rPct = document.getElementById('rightLiverPct');
                    if (rEl) rEl.textContent = liver.right_liver_volume_cm3.toLocaleString('fr-FR');
                    if (rPct) rPct.textContent = `${liver.right_liver_pct}% du foie total`;
                }
                if (liver.left_liver_volume_cm3 !== undefined) {
                    const lEl = document.getElementById('leftLiverVol');
                    const lPct = document.getElementById('leftLiverPct');
                    if (lEl) lEl.textContent = liver.left_liver_volume_cm3.toLocaleString('fr-FR');
                    if (lPct) lPct.textContent = `${liver.left_liver_pct}% du foie total`;
                }
                // Lobe gauche / Secteur latéral (Seg. II + III)
                const latEl = document.getElementById('leftLatLiverVol');
                const latPct = document.getElementById('leftLatLiverPct');
                let latVol = liver.left_lateral_volume_cm3;
                let latP = liver.left_lateral_pct;
                if (latVol === undefined && couinaudSegments) {
                    const s2 = (couinaudSegments.liver_segment_2 && couinaudSegments.liver_segment_2.volume_cm3) || 0;
                    const s3 = (couinaudSegments.liver_segment_3 && couinaudSegments.liver_segment_3.volume_cm3) || 0;
                    latVol = Math.round((s2 + s3) * 100) / 100;
                    latP = liver.volume_cm3 ? Math.round((latVol / liver.volume_cm3) * 1000) / 10 : 0;
                }
                if (latEl && latVol !== undefined) latEl.textContent = latVol.toLocaleString('fr-FR');
                if (latPct && latP !== undefined) latPct.textContent = `${latP}% du foie total`;

                if (liver.caudate_lobe_volume_cm3 !== undefined) {
                    const cEl = document.getElementById('caudateLiverVol');
                    const cPct = document.getElementById('caudateLiverPct');
                    if (cEl) cEl.textContent = liver.caudate_lobe_volume_cm3.toLocaleString('fr-FR');
                    if (cPct) cPct.textContent = `${liver.caudate_lobe_pct}% du foie total`;
                }

                // Remplissage du tableau des 8 segments
                if (couinaudTbody) {
                    couinaudTbody.innerHTML = '';
                    Object.entries(couinaudSegments).forEach(([key, seg]) => {
                        const tr = document.createElement('tr');
                        const colorHex = seg.color_hex || '#38bdf8';
                        const segId = seg.id || key;
                        tr.innerHTML = `
                            <td style="font-weight: 600;">
                                <span class="segment-color-dot" style="background-color: ${colorHex}; box-shadow: 0 0 6px ${colorHex}88;"></span>
                                <span style="color: ${colorHex}; font-weight: 700;">${seg.couinaud_label || seg.name}</span>
                            </td>
                            <td>${seg.anatomical_description || '--'}</td>
                            <td><span style="background:rgba(255,255,255,0.06);padding:0.2rem 0.5rem;border-radius:4px;font-size:0.75rem;">${seg.lobe || 'Foie'}</span></td>
                            <td style="text-align: right; font-weight: 600;">${seg.volume_cm3 ? seg.volume_cm3.toLocaleString('fr-FR') : '--'} cm³</td>
                            <td style="text-align: right; color: var(--accent-liver); font-weight: 600;">${seg.pct_of_liver !== undefined ? `${seg.pct_of_liver}%` : '--'}</td>
                            <td style="text-align: right; color: var(--text-dim);">${seg.mean_hu !== null && seg.mean_hu !== undefined ? `${seg.mean_hu} HU` : '--'}</td>
                            <td style="text-align: center;">
                                <button type="button" class="btn btn-sm btn-seg-3d-toggle active" data-seg-id="${segId}" title="Afficher ou masquer ce segment en 3D">
                                    <span class="seg-toggle-icon">👁️</span> <span class="seg-toggle-label">Visible</span>
                                </button>
                            </td>
                        `;
                        couinaudTbody.appendChild(tr);
                    });

                    // Délégation d'événement pour basculer les segments depuis le tableau
                    couinaudTbody.onclick = (e) => {
                        const btn = e.target.closest('.btn-seg-3d-toggle');
                        if (!btn) return;
                        const segId = btn.getAttribute('data-seg-id');
                        if (!segId || !stlViewerInstance) return;
                        const isVisible = stlViewerInstance.toggleMeshVisibility(segId);
                        updateSegmentUIState(segId, isVisible);
                    };
                }
            } else {
                if (couinaudSec) couinaudSec.style.display = 'none';
            }

            // 3. Initialisation et chargement du visualiseur 3D STL
            try {
                init3DViewer(jobId, result.model_3d);
            } catch (err3d) {
                console.error("Erreur init3DViewer :", err3d);
            }

            // 4. Coupes Axiales scanner 2D
            try {
                renderSliceGallery(jobId, result.slice_previews);
            } catch (errSlices) {
                console.error("Erreur renderSliceGallery :", errSlices);
            }

            // 5. Tableaux Patient & Acquisition
            try {
                renderMetadataTables(result);
            } catch (errMeta) {
                console.error("Erreur renderMetadataTables :", errMeta);
            }

            // 6. Liens de téléchargement et Reconstructions MPR
            btnDownloadStl.href = `/api/files/${jobId}/liver.stl`;
            btnDownloadJson.href = `/api/files/${jobId}/result.json`;
            btnOpenReport.href = `/api/report/${jobId}`;

            if (btnOpenMprNewWindow) {
                btnOpenMprNewWindow.href = `/mpr-viewer/${jobId}`;
            }
            if (btnGoToMpr) {
                btnGoToMpr.onclick = () => {
                    const mprTabBtn = document.querySelector('[data-tab="mpr"]');
                    if (mprTabBtn) mprTabBtn.click();
                };
            }
            if (btnMprOpenStandalone) {
                btnMprOpenStandalone.onclick = () => {
                    window.open(`/mpr-viewer/${jobId}`, '_blank');
                };
            }
            const mprIframe = document.getElementById('mprIframe');
            if (mprIframe) {
                mprIframe.src = `/mpr-viewer/${jobId}`;
            }

            // Basculer automatiquement vers l'onglet résultats
            resultsTabBtn.click();

        } catch (err) {
            console.error("Erreur affichage résultats :", err);
        }
    }

    // Mise à jour de l'affichage du Volume Théorique (Vauthey), des Critères de Lille, de la Stéatose et du Ratio Foie/Rate
    function updateBiometricsDisplay(theo, lille, liver, patientInfo = {}, steat = null, hs = null, spleen = null, fullResult = null) {
        // 1. KPI Vauthey
        if (theo && theo.tlv_vauthey_cm3) {
            kpiTheoVol.textContent = `${theo.tlv_vauthey_cm3.toLocaleString('fr-FR')} cm³`;
            kpiTheoRatio.textContent = `Ratio mesuré / attendu : ${theo.ratio_measured_to_theoretical_pct}%`;
        } else {
            kpiTheoVol.textContent = '--';
            kpiTheoRatio.textContent = 'Poids/Taille non renseignés';
        }

        // 2. Section Bilan de Lille & Ratios pondéraux
        if (lilleSection) {
            lilleSection.style.display = 'block';

            const patientWeight = (lille && lille.patient_weight_kg) || patientInfo.patient_weight || null;
            if (lillePatientWeightDisp) {
                lillePatientWeightDisp.textContent = patientWeight ? patientWeight : '--';
            }

            // Pré-remplir les champs du simulateur
            if (quickWeight && patientWeight) {
                quickWeight.value = patientWeight;
            }
            const patientHeight = (theo && theo.patient_height_cm) || patientInfo.patient_height || null;
            if (quickHeight && patientHeight) {
                quickHeight.value = patientHeight;
            }

            if (lille) {
                if (lilleTotalBwPct) lilleTotalBwPct.textContent = (lille.total_liver_bw_pct !== undefined && lille.total_liver_bw_pct !== null) ? lille.total_liver_bw_pct : '--';
                if (lilleRightBwPct) lilleRightBwPct.textContent = (lille.right_liver_bw_pct !== undefined && lille.right_liver_bw_pct !== null) ? lille.right_liver_bw_pct : '--';
                if (lilleLeftBwPct) lilleLeftBwPct.textContent = (lille.left_liver_bw_pct !== undefined && lille.left_liver_bw_pct !== null) ? lille.left_liver_bw_pct : '--';
                if (lilleLeftLatBwPct) lilleLeftLatBwPct.textContent = (lille.left_lateral_lobe_bw_pct !== undefined && lille.left_lateral_lobe_bw_pct !== null) ? lille.left_lateral_lobe_bw_pct : '--';

                // Badges de sécurité (seuil 0.5% sur foie non-cirrhotique)
                if (badgeRightSafety) {
                    if (lille.right_liver_safe === true) {
                        badgeRightSafety.className = 'badge badge-success';
                        badgeRightSafety.textContent = '≥ 0.5% Sécurisé';
                    } else if (lille.right_liver_safe === false) {
                        badgeRightSafety.className = 'badge badge-warning';
                        badgeRightSafety.textContent = '< 0.5% Risque PHLF';
                    } else {
                        badgeRightSafety.className = 'badge';
                        badgeRightSafety.textContent = '--';
                    }
                }

                if (badgeLeftSafety) {
                    if (lille.left_liver_safe === true) {
                        badgeLeftSafety.className = 'badge badge-success';
                        badgeLeftSafety.textContent = '≥ 0.5% Sécurisé';
                    } else if (lille.left_liver_safe === false) {
                        badgeLeftSafety.className = 'badge badge-warning';
                        badgeLeftSafety.textContent = '< 0.5% Risque PHLF';
                    } else {
                        badgeLeftSafety.className = 'badge';
                        badgeLeftSafety.textContent = '--';
                    }
                }

                if (badgeLeftLatSafety) {
                    if (lille.left_lateral_safe === true) {
                        badgeLeftLatSafety.className = 'badge badge-success';
                        badgeLeftLatSafety.textContent = '≥ 0.5% Sécurisé';
                    } else if (lille.left_lateral_safe === false) {
                        badgeLeftLatSafety.className = 'badge badge-warning';
                        badgeLeftLatSafety.textContent = '< 0.5% Risque PHLF';
                    } else {
                        badgeLeftLatSafety.className = 'badge';
                        badgeLeftLatSafety.textContent = '--';
                    }
                }

                // Sous-titres % du poids dans les 4 cartes sectorielles Couinaud
                const rBw = document.getElementById('rightLiverBwSub');
                if (rBw) rBw.textContent = (lille.right_liver_bw_pct !== undefined && lille.right_liver_bw_pct !== null) ? `${lille.right_liver_bw_pct}% du poids` : '-- % du poids';

                const lBw = document.getElementById('leftLiverBwSub');
                if (lBw) lBw.textContent = (lille.left_liver_bw_pct !== undefined && lille.left_liver_bw_pct !== null) ? `${lille.left_liver_bw_pct}% du poids` : '-- % du poids';

                const lLatBw = document.getElementById('leftLatLiverBwSub');
                if (lLatBw) lLatBw.textContent = (lille.left_lateral_lobe_bw_pct !== undefined && lille.left_lateral_lobe_bw_pct !== null) ? `${lille.left_lateral_lobe_bw_pct}% du poids` : '-- % du poids';

                const cBw = document.getElementById('caudateLiverBwSub');
                if (cBw) cBw.textContent = (lille.caudate_lobe_bw_pct !== undefined && lille.caudate_lobe_bw_pct !== null) ? `${lille.caudate_lobe_bw_pct}% du poids` : '-- % du poids';
            } else {
                if (lilleTotalBwPct) lilleTotalBwPct.textContent = '--';
                if (lilleRightBwPct) lilleRightBwPct.textContent = '--';
                if (lilleLeftBwPct) lilleLeftBwPct.textContent = '--';
                if (lilleLeftLatBwPct) lilleLeftLatBwPct.textContent = '--';
                if (badgeRightSafety) badgeRightSafety.textContent = 'Poids requis';
                if (badgeLeftSafety) badgeLeftSafety.textContent = 'Poids requis';
                if (badgeLeftLatSafety) badgeLeftLatSafety.textContent = 'Poids requis';
                
                ['rightLiverBwSub', 'leftLiverBwSub', 'leftLatLiverBwSub', 'caudateLiverBwSub'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.textContent = '-- % du poids';
                });
            }
        }

        // 3. Section Stéatose & Atténuation parenchymateuse
        if (steat) {
            if (steatStatus) steatStatus.textContent = steat.status || 'Densité normale';
            if (steatGradeBadge) {
                steatGradeBadge.textContent = steat.grade || 'Grade 0 (Absence)';
                steatGradeBadge.className = `badge ${steat.warning ? 'badge-warning' : 'badge-success'}`;
                if (steat.color) steatGradeBadge.style.backgroundColor = steat.color;
            }
            if (steatLiverHu) steatLiverHu.textContent = steat.mean_hu !== undefined ? `${steat.mean_hu} HU` : '-- HU';
            if (steatInfiltration) steatInfiltration.textContent = steat.infiltration_est || '< 5%';
            if (steatSpleenHu) steatSpleenHu.textContent = (steat.spleen_mean_hu !== undefined && steat.spleen_mean_hu !== null) ? `${steat.spleen_mean_hu} HU` : 'Non mesurée';
            if (steatDiffHu) {
                if (steat.liver_spleen_diff_hu !== undefined && steat.liver_spleen_diff_hu !== null) {
                    const sign = steat.liver_spleen_diff_hu > 0 ? '+' : '';
                    steatDiffHu.textContent = `${sign}${steat.liver_spleen_diff_hu} HU`;
                    steatDiffHu.style.color = steat.liver_spleen_diff_hu < -10 ? '#ef4444' : (steat.liver_spleen_diff_hu < 0 ? '#f59e0b' : '#34d399');
                } else {
                    steatDiffHu.textContent = '--';
                    steatDiffHu.style.color = 'inherit';
                }
            }
            if (steatNoteText) {
                let note = steat.note || '';
                if (steat.differential_interpretation) {
                    note += ` • ${steat.differential_interpretation}`;
                }
                steatNoteText.textContent = note;
            }
        } else if (liver && liver.mean_hu !== null && liver.mean_hu !== undefined) {
            if (steatLiverHu) steatLiverHu.textContent = `${liver.mean_hu} HU`;
        }

        // 4. Section Balance Volumétrique Hépato-Splénique (Ratio Foie / Rate)
        const spleenVol = (hs && hs.spleen_volume_cm3) || (spleen && spleen.volume_cm3) || null;
        if (hs) {
            if (hsRatioVal) hsRatioVal.textContent = hs.ratio;
            if (hsRatioBadge) {
                hsRatioBadge.textContent = hs.status || 'Normal';
                hsRatioBadge.className = `badge ${hs.warning ? 'badge-warning' : 'badge-success'}`;
            }
            if (hsLiverVolDisp) hsLiverVolDisp.textContent = `${(hs.liver_volume_cm3 || liver.volume_cm3 || 0).toLocaleString('fr-FR')} cm³`;
            if (hsSpleenVolDisp) hsSpleenVolDisp.textContent = `${(hs.spleen_volume_cm3 || spleenVol || 0).toLocaleString('fr-FR')} cm³`;
            if (hsInterpretationText) hsInterpretationText.textContent = hs.interpretation || '--';
            if (quickSpleenVol && hs.spleen_volume_cm3) quickSpleenVol.value = hs.spleen_volume_cm3;

            if (kpiSpleenCard) {
                kpiSpleenCard.style.display = 'block';
                if (kpiSpleenVol) kpiSpleenVol.textContent = `${hs.spleen_volume_cm3.toLocaleString('fr-FR')} cm³`;
                if (kpiHsRatio) kpiHsRatio.textContent = `Ratio Foie/Rate : ${hs.ratio} (${hs.status})`;
            }
        } else if (spleenVol) {
            const lVol = liver.volume_cm3 || 0;
            const rat = lVol > 0 ? (lVol / spleenVol).toFixed(2) : '--';
            if (hsRatioVal) hsRatioVal.textContent = rat;
            if (hsLiverVolDisp) hsLiverVolDisp.textContent = `${lVol.toLocaleString('fr-FR')} cm³`;
            if (hsSpleenVolDisp) hsSpleenVolDisp.textContent = `${spleenVol.toLocaleString('fr-FR')} cm³`;
            if (quickSpleenVol) quickSpleenVol.value = spleenVol;
            if (kpiSpleenCard) {
                kpiSpleenCard.style.display = 'block';
                if (kpiSpleenVol) kpiSpleenVol.textContent = `${spleenVol.toLocaleString('fr-FR')} cm³`;
                if (kpiHsRatio) kpiHsRatio.textContent = `Ratio Foie/Rate : ${rat}`;
            }
        } else {
            if (hsRatioVal) hsRatioVal.textContent = '--';
            if (hsRatioBadge) {
                hsRatioBadge.textContent = 'Non mesurée';
                hsRatioBadge.className = 'badge';
            }
            if (hsLiverVolDisp) hsLiverVolDisp.textContent = liver.volume_cm3 ? `${liver.volume_cm3.toLocaleString('fr-FR')} cm³` : '--';
            if (hsSpleenVolDisp) hsSpleenVolDisp.textContent = 'Non mesuré';
            if (hsInterpretationText) hsInterpretationText.textContent = "Rate non segmentée. Indiquez le volume de la rate ci-dessus pour calculer le ratio hépato-splénique.";
        }

        // 5. Section Charge Tumorale & Lésions Focales (Nath & Saha, 2026 / 3D-IRCADb-01)
        const tum = (fullResult && fullResult.tumour_analysis) || (liver && liver.tumour_analysis) || null;
        const tumourCard = document.getElementById('tumourCardContainer');
        const tumourBurdenVal = document.getElementById('tumourBurdenVal');
        const tumourVolDisp = document.getElementById('tumourVolDisp');
        const functionalLiverVolDisp = document.getElementById('functionalLiverVolDisp');
        const tumourStatusBadge = document.getElementById('tumourStatusBadge');
        const tumourNoteText = document.getElementById('tumourNoteText');

        if (tum && tum.detected) {
            if (tumourCard) tumourCard.style.display = 'flex';
            if (tumourBurdenVal) tumourBurdenVal.textContent = `${tum.tumour_burden_pct}%`;
            if (tumourVolDisp) tumourVolDisp.textContent = `${(tum.total_tumour_volume_cm3 || 0).toLocaleString('fr-FR')} cm³`;
            if (functionalLiverVolDisp) functionalLiverVolDisp.textContent = `${(tum.functional_liver_volume_cm3 || 0).toLocaleString('fr-FR')} cm³`;
            if (tumourStatusBadge) {
                tumourStatusBadge.textContent = tum.location ? `${tum.location}` : 'Confinement 3D';
                tumourStatusBadge.className = 'badge badge-warning';
            }
            if (tumourNoteText) {
                tumourNoteText.textContent = `Charge tumorale de ${tum.tumour_burden_pct}%. Le parenchyme fonctionnel sain net (${tum.functional_liver_volume_cm3} cm³) est déduit pour sécuriser les critères de Lille.`;
            }

            // 5.b Marges Chirurgicales 3D (rmsandu / segmentation-eval 2026)
            const marginsBlock = document.getElementById('surgicalMarginsBlock');
            const sm = (fullResult && fullResult.surgical_margins) || null;
            if (sm && sm.calculated && sm.margins) {
                if (marginsBlock) marginsBlock.style.display = 'block';
                const r0Badge = document.getElementById('surgicalR0Badge');
                if (r0Badge) {
                    r0Badge.textContent = sm.r0_status || 'R0';
                    r0Badge.className = `badge ${sm.r0_badge || 'badge-info'}`;
                }
                const mPV = document.getElementById('marginPVVal');
                const mHV = document.getElementById('marginHVVal');
                const mArt = document.getElementById('marginArtVal');
                const mIVC = document.getElementById('marginIVCVal');
                const mCap = document.getElementById('marginCapsuleVal');

                if (mPV && sm.margins.portal_vein) mPV.textContent = `${sm.margins.portal_vein.distance_mm} mm`;
                if (mHV && sm.margins.hepatic_vein) mHV.textContent = `${sm.margins.hepatic_vein.distance_mm} mm`;
                if (mArt && sm.margins.hepatic_artery) mArt.textContent = `${sm.margins.hepatic_artery.distance_mm} mm`;
                if (mIVC && sm.margins.inferior_vena_cava) mIVC.textContent = `${sm.margins.inferior_vena_cava.distance_mm} mm`;
                if (mCap && sm.margins.liver_capsule) mCap.textContent = `${sm.margins.liver_capsule.distance_mm} mm`;
            } else if (marginsBlock) {
                marginsBlock.style.display = 'none';
            }
        } else if (tumourCard) {
            const marginsBlock = document.getElementById('surgicalMarginsBlock');
            if (marginsBlock) marginsBlock.style.display = 'none';
            if (tumourBurdenVal) tumourBurdenVal.textContent = '0.00 %';
            if (tumourVolDisp) tumourVolDisp.textContent = '0.0 cm³';
            if (functionalLiverVolDisp) functionalLiverVolDisp.textContent = liver.volume_cm3 ? `${liver.volume_cm3.toLocaleString('fr-FR')} cm³` : '--';
            if (tumourStatusBadge) {
                tumourStatusBadge.textContent = 'Parenchyme Sain';
                tumourStatusBadge.className = 'badge badge-success';
            }
            if (tumourNoteText) {
                tumourNoteText.textContent = 'Aucune lésion focale significative détectée. Parenchyme homogène.';
            }
        }
    }

    // Gestion du clic sur "Actualiser Ratios" (simulateur biométrique & volumétrique)
    if (btnUpdateBiometrics) {
        btnUpdateBiometrics.addEventListener('click', async () => {
            if (!currentJobId) {
                alert("Veuillez d'abord ouvrir ou exécuter une analyse.");
                return;
            }

            const w = parseFloat(quickWeight?.value);
            const h = parseFloat(quickHeight?.value) || null;
            const spleenVol = parseFloat(quickSpleenVol?.value) || null;
            const sex = document.getElementById('patientSex')?.value || "M";

            if (!w && !spleenVol) {
                alert("Veuillez saisir au moins le poids en kg (ex: 70) ou le volume de rate en cm³ (ex: 220).");
                return;
            }

            btnUpdateBiometrics.disabled = true;
            const originalHtml = btnUpdateBiometrics.innerHTML;
            btnUpdateBiometrics.innerHTML = `⏳ Calcul...`;

            try {
                const res = await fetch(`/api/job/${currentJobId}/biometrics`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        patient_weight: w || null,
                        patient_height: h || null,
                        patient_sex: sex,
                        spleen_volume_cm3: spleenVol || null
                    })
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || "Erreur de mise à jour");
                }

                const data = await res.json();
                if (data.success) {
                    updateBiometricsDisplay(
                        data.theoretical_volume,
                        data.lille_criteria,
                        data.liver,
                        {
                            patient_weight: w,
                            patient_height: h,
                            patient_sex: sex
                        },
                        data.steatosis_evaluation,
                        data.hepato_splenic_ratio,
                        data.spleen,
                        data
                    );
                    btnUpdateBiometrics.innerHTML = `✓ Ratios actualisés !`;
                    setTimeout(() => {
                        btnUpdateBiometrics.innerHTML = originalHtml;
                        btnUpdateBiometrics.disabled = false;
                    }, 1800);
                }
            } catch (err) {
                alert(`Erreur : ${err.message}`);
                btnUpdateBiometrics.innerHTML = originalHtml;
                btnUpdateBiometrics.disabled = false;
            }
        });
    }

    // Synchronisation de l'état de visibilité d'un segment entre les pastilles 3D et le tableau de données
    function updateSegmentUIState(segId, isVisible) {
        // 1. Pastille dans la barre de contrôle 3D
        const pill = document.querySelector(`.segment-pill[data-seg-id="${segId}"]`);
        if (pill) {
            pill.classList.toggle('active', isVisible);
            pill.classList.toggle('inactive', !isVisible);
            const eye = pill.querySelector('.segment-pill-eye');
            if (eye) eye.textContent = isVisible ? '👁️' : '🚫';
        }
        // 2. Bouton dans le tableau Couinaud
        const tblBtn = document.querySelector(`.btn-seg-3d-toggle[data-seg-id="${segId}"]`);
        if (tblBtn) {
            tblBtn.classList.toggle('active', isVisible);
            tblBtn.classList.toggle('inactive', !isVisible);
            const icon = tblBtn.querySelector('.seg-toggle-icon');
            const label = tblBtn.querySelector('.seg-toggle-label');
            if (icon) icon.textContent = isVisible ? '👁️' : '🚫';
            if (label) label.textContent = isVisible ? 'Visible' : 'Masqué';
        }
        // 3. Mise à jour du compteur global
        updateVisibleSegmentsCount();
    }

    function updateVisibleSegmentsCount() {
        const countEl = document.getElementById('segmentsVisibleCount');
        if (!countEl || !stlViewerInstance || !stlViewerInstance.meshes || stlViewerInstance.meshes.length === 0) return;
        const total = stlViewerInstance.meshes.length;
        const visible = stlViewerInstance.meshes.filter(m => m.visible).length;
        countEl.textContent = `${visible}/${total} visibles`;
        if (visible === 0) {
            countEl.style.color = '#ef4444';
            countEl.style.borderColor = 'rgba(239, 68, 68, 0.4)';
            countEl.style.background = 'rgba(239, 68, 68, 0.15)';
        } else if (visible === total) {
            countEl.style.color = '#38bdf8';
            countEl.style.borderColor = 'rgba(56, 189, 248, 0.3)';
            countEl.style.background = 'rgba(56, 189, 248, 0.15)';
        } else {
            countEl.style.color = '#fbbf24';
            countEl.style.borderColor = 'rgba(251, 191, 36, 0.4)';
            countEl.style.background = 'rgba(251, 191, 36, 0.15)';
        }
    }

    // Initialisation du visualiseur 3D (Gestion Multi-Segments ou Modèle Unifié)
    async function init3DViewer(jobId, modelInfo) {
        if (!modelInfo || !modelInfo.available) {
            document.getElementById('viewer3dContainer').innerHTML = `
                <div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);">
                    Modèle 3D non disponible.
                </div>`;
            return;
        }

        if (!stlViewerInstance) {
            stlViewerInstance = new MedicalSTLViewer('stlCanvas');
            setupViewerToolbar();
        }

        const modelInfoText = document.getElementById('modelInfoText');
        const legendContainer = document.getElementById('segments3DLegend');
        const pillsContainer = document.getElementById('segmentsPillsContainer');
        const vesselsLegend = document.getElementById('vessels3DLegend');
        const vesselsPills = document.getElementById('vesselsPillsContainer');
        const btnToggleParenchyma = document.getElementById('btnToggleParenchymaOpacity');

        const hasSegments = (modelInfo.has_segments && modelInfo.segments && modelInfo.segments.length > 0);
        const hasVessels = (modelInfo.has_vessels && modelInfo.vessels && modelInfo.vessels.length > 0);

        // Cas A : Multi-segments Couinaud ou Vaisseaux 3D disponibles
        if (hasSegments || hasVessels) {
            const countInfo = [];
            if (hasSegments) countInfo.push(`${modelInfo.segments.length} segments`);
            if (hasVessels) countInfo.push(`${modelInfo.vessels.length} structures vasculaires`);
            if (modelInfoText) modelInfoText.textContent = `Chargement 3D (${countInfo.join(', ')})...`;
            
            const segmentsToLoad = [];

            if (hasSegments) {
                modelInfo.segments.forEach(seg => {
                    segmentsToLoad.push({
                        id: seg.id,
                        name: seg.name,
                        number: seg.number,
                        subname: seg.subname,
                        lobe: seg.lobe,
                        color_hex: seg.color_hex,
                        color_rgb: seg.color_rgb,
                        volume_cm3: seg.volume_cm3,
                        pct_of_liver: seg.pct_of_liver,
                        is_vessel: false,
                        url: `/api/files/${jobId}/${seg.filename}`
                    });
                });
            }

            if (hasVessels) {
                modelInfo.vessels.forEach(v => {
                    segmentsToLoad.push({
                        id: v.id,
                        name: v.name,
                        subname: v.subname || '',
                        color_hex: v.color_hex || '#38bdf8',
                        color_rgb: v.color_rgb || [56, 189, 248],
                        is_vessel: true,
                        visible: true,
                        url: `/api/files/${jobId}/${v.filename}`
                    });
                });
            }

            try {
                await stlViewerInstance.loadSegments(segmentsToLoad);

                if (modelInfoText) {
                    modelInfoText.textContent = `${countInfo.join(' • ')} • ${stlViewerInstance.trianglesCount.toLocaleString('fr-FR')} polygones`;
                }

                // Si des vaisseaux sont présents, activer par défaut la semi-transparence du parenchyme hépatique
                if (hasVessels) {
                    stlViewerInstance.setParenchymaOpacity(0.32);
                    if (btnToggleParenchyma) {
                        btnToggleParenchyma.textContent = '🪟 Translucide';
                        btnToggleParenchyma.style.borderColor = '#38bdf8';
                        btnToggleParenchyma.style.color = '#38bdf8';
                    }
                }

                // 1. Légende et pastilles des segments de Couinaud
                if (hasSegments && legendContainer && pillsContainer) {
                    legendContainer.style.display = 'flex';
                    pillsContainer.innerHTML = '';

                    modelInfo.segments.forEach(seg => {
                        const pill = document.createElement('button');
                        pill.type = 'button';
                        pill.className = 'segment-pill active';
                        pill.setAttribute('data-seg-id', seg.id);
                        pill.style.setProperty('--pill-color', seg.color_hex || '#38bdf8');
                        pill.title = `${seg.name} (${seg.subname}) - Cliquer pour masquer / afficher en 3D`;
                        pill.innerHTML = `
                            <span class="segment-pill-eye">👁️</span>
                            <span class="segment-pill-dot" style="background:${seg.color_hex || '#38bdf8'};box-shadow:0 0 6px ${seg.color_hex || '#38bdf8'};"></span>
                            <span class="segment-pill-name">${seg.number ? 'Seg ' + seg.number : seg.name}</span>
                            <span class="segment-pill-vol">${seg.volume_cm3} cm³</span>
                        `;

                        pill.addEventListener('click', () => {
                            const isVisible = stlViewerInstance.toggleMeshVisibility(seg.id);
                            updateSegmentUIState(seg.id, isVisible);
                        });

                        pillsContainer.appendChild(pill);
                    });

                    // Synchronisation initiale de l'état et du compteur
                    modelInfo.segments.forEach(seg => {
                        updateSegmentUIState(seg.id, true);
                    });
                    updateVisibleSegmentsCount();

                    // Boutons tout afficher / tout masquer segments
                    const btnShowAll = document.getElementById('btnShowAllSegments');
                    const btnHideAll = document.getElementById('btnHideAllSegments');

                    if (btnShowAll) {
                        btnShowAll.onclick = () => {
                            modelInfo.segments.forEach(s => {
                                stlViewerInstance.setMeshVisibility(s.id, true);
                                updateSegmentUIState(s.id, true);
                            });
                        };
                    }

                    if (btnHideAll) {
                        btnHideAll.onclick = () => {
                            modelInfo.segments.forEach(s => {
                                stlViewerInstance.setMeshVisibility(s.id, false);
                                updateSegmentUIState(s.id, false);
                            });
                        };
                    }

                    // Boutons de filtres anatomiques sectoriels
                    document.querySelectorAll('.btn-segment-preset').forEach(btn => {
                        btn.onclick = () => {
                            const preset = btn.getAttribute('data-preset');
                            let targetIds = [];
                            if (preset === 'right') {
                                targetIds = ['liver_segment_5', 'liver_segment_6', 'liver_segment_7', 'liver_segment_8'];
                            } else if (preset === 'left') {
                                targetIds = ['liver_segment_2', 'liver_segment_3', 'liver_segment_4'];
                            } else if (preset === 'left_lateral') {
                                targetIds = ['liver_segment_2', 'liver_segment_3'];
                            } else if (preset === 'caudate') {
                                targetIds = ['liver_segment_1'];
                            }

                            if (stlViewerInstance && stlViewerInstance.meshes) {
                                modelInfo.segments.forEach(s => {
                                    const shouldShow = targetIds.includes(s.id);
                                    stlViewerInstance.setMeshVisibility(s.id, shouldShow);
                                    updateSegmentUIState(s.id, shouldShow);
                                });
                            }
                        };
                    });
                } else if (legendContainer) {
                    legendContainer.style.display = 'none';
                }

                // 2. Légende et pastilles des vaisseaux hépatiques 3D
                if (hasVessels && vesselsLegend && vesselsPills) {
                    vesselsLegend.style.display = 'flex';
                    vesselsPills.innerHTML = '';

                    modelInfo.vessels.forEach(v => {
                        const vPill = document.createElement('button');
                        vPill.type = 'button';
                        vPill.className = 'segment-pill active';
                        vPill.setAttribute('data-vessel-id', v.id);
                        vPill.style.setProperty('--pill-color', v.color_hex || '#38bdf8');
                        vPill.title = `${v.name} (${v.subname}) - Cliquer pour masquer / afficher en 3D`;
                        vPill.innerHTML = `
                            <span class="segment-pill-eye">👁️</span>
                            <span class="segment-pill-dot" style="background:${v.color_hex || '#38bdf8'};box-shadow:0 0 6px ${v.color_hex || '#38bdf8'};"></span>
                            <span class="segment-pill-name" style="font-weight:700;">${v.name}</span>
                        `;

                        vPill.onclick = () => {
                            const isVisible = stlViewerInstance.toggleMeshVisibility(v.id);
                            vPill.classList.toggle('active', isVisible);
                            vPill.classList.toggle('hidden-seg', !isVisible);
                            const eye = vPill.querySelector('.segment-pill-eye');
                            if (eye) eye.textContent = isVisible ? '👁️' : '🚫';
                        };

                        vesselsPills.appendChild(vPill);
                    });

                    const btnShowAllVessels = document.getElementById('btnShowAllVessels');
                    const btnHideAllVessels = document.getElementById('btnHideAllVessels');

                    if (btnShowAllVessels) {
                        btnShowAllVessels.onclick = () => {
                            modelInfo.vessels.forEach(v => {
                                stlViewerInstance.setMeshVisibility(v.id, true);
                                const p = vesselsPills.querySelector(`[data-vessel-id="${v.id}"]`);
                                if (p) {
                                    p.classList.add('active');
                                    p.classList.remove('hidden-seg');
                                    const eye = p.querySelector('.segment-pill-eye');
                                    if (eye) eye.textContent = '👁️';
                                }
                            });
                        };
                    }

                    if (btnHideAllVessels) {
                        btnHideAllVessels.onclick = () => {
                            modelInfo.vessels.forEach(v => {
                                stlViewerInstance.setMeshVisibility(v.id, false);
                                const p = vesselsPills.querySelector(`[data-vessel-id="${v.id}"]`);
                                if (p) {
                                    p.classList.remove('active');
                                    p.classList.add('hidden-seg');
                                    const eye = p.querySelector('.segment-pill-eye');
                                    if (eye) eye.textContent = '🚫';
                                }
                            });
                        };
                    }
                } else if (vesselsLegend) {
                    vesselsLegend.style.display = 'none';
                }

            } catch (err) {
                console.warn("Échec du chargement 3D multi-structures, repli sur liver.stl unifié:", err);
                loadFallbackUnifiedSTL(jobId);
            }
        } else {
            // Cas B : Foie unifié (pas de segmentation Couinaud)
            if (legendContainer) legendContainer.style.display = 'none';
            if (vesselsLegend) vesselsLegend.style.display = 'none';
            loadFallbackUnifiedSTL(jobId);
        }
    }

    function loadFallbackUnifiedSTL(jobId) {
        const stlUrl = `/api/files/${jobId}/liver.stl`;
        const modelInfoText = document.getElementById('modelInfoText');
        stlViewerInstance.loadSTLFromUrl(stlUrl)
            .then(() => {
                if (modelInfoText) {
                    modelInfoText.textContent = `Maillage 3D : ${stlViewerInstance.trianglesCount.toLocaleString('fr-FR')} polygones`;
                }
            })
            .catch(err => {
                console.error("Impossible de charger le STL 3D :", err);
            });
    }

    function setupViewerToolbar() {
        document.getElementById('btnResetView')?.addEventListener('click', () => {
            stlViewerInstance?.resetView();
        });
        document.getElementById('btnToggleRotate')?.addEventListener('click', () => {
            stlViewerInstance?.toggleAutoRotate();
        });
        document.getElementById('btnToggleWireframe')?.addEventListener('click', () => {
            stlViewerInstance?.toggleWireframe();
        });
        document.getElementById('btnToggleParenchymaOpacity')?.addEventListener('click', () => {
            if (!stlViewerInstance) return;
            const isTrans = stlViewerInstance.toggleParenchymaOpacity();
            const btn = document.getElementById('btnToggleParenchymaOpacity');
            if (btn) {
                btn.textContent = isTrans ? '🪟 Translucide' : '🧱 Opaque';
                btn.style.borderColor = isTrans ? '#38bdf8' : 'var(--border-color)';
                btn.style.color = isTrans ? '#38bdf8' : '#fff';
            }
        });
        document.getElementById('btnIsolatedVascularView')?.addEventListener('click', () => {
            if (!stlViewerInstance) return;
            const isIsolated = stlViewerInstance.toggleIsolatedVascularView();
            const btn = document.getElementById('btnIsolatedVascularView');
            if (btn) {
                btn.style.background = isIsolated ? 'rgba(56, 189, 248, 0.28)' : 'rgba(56, 189, 248, 0.08)';
                btn.style.borderColor = isIsolated ? '#38bdf8' : 'rgba(56, 189, 248, 0.5)';
                btn.innerHTML = isIsolated ? '🫀 Vue Vasculaire Active (100%)' : '🫀 Vue Vasculaire Isolée';
            }
            document.querySelectorAll('.btn-parenchyma-opacity').forEach(b => {
                const op = parseFloat(b.getAttribute('data-opacity'));
                b.classList.toggle('active', isIsolated ? (op === 0.0) : (op === 0.32));
            });
        });
        document.querySelectorAll('.btn-parenchyma-opacity').forEach(btn => {
            btn.addEventListener('click', () => {
                if (!stlViewerInstance) return;
                const op = parseFloat(btn.getAttribute('data-opacity'));
                if (op === 0.0) {
                    stlViewerInstance.setIsolatedVascularView(true);
                } else {
                    stlViewerInstance.setIsolatedVascularView(false);
                    stlViewerInstance.setParenchymaOpacity(op);
                }
                document.querySelectorAll('.btn-parenchyma-opacity').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const isoBtn = document.getElementById('btnIsolatedVascularView');
                if (isoBtn) {
                    isoBtn.style.background = (op === 0.0) ? 'rgba(56, 189, 248, 0.28)' : 'rgba(56, 189, 248, 0.08)';
                    isoBtn.innerHTML = (op === 0.0) ? '🫀 Vue Vasculaire Active (100%)' : '🫀 Vue Vasculaire Isolée';
                }
            });
        });
        document.querySelectorAll('.btn-view-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                const view = btn.getAttribute('data-view');
                stlViewerInstance?.setAnatomicalView(view);
            });
        });
        document.querySelectorAll('.btn-color-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                const color = btn.getAttribute('data-color');
                stlViewerInstance?.setPresetColor(color);
            });
        });
        document.getElementById('btnCapture3D')?.addEventListener('click', () => {
            if (!stlViewerInstance) return;
            const dataUrl = stlViewerInstance.captureScreenshot();
            const a = document.createElement('a');
            a.href = dataUrl;
            a.download = `vue_3d_foie_${currentJobId || 'capture'}.png`;
            a.click();
        });
    }

    // --- Gestion de la Rotation & de l'Orientation des Coupes Axiales Scanner (CT / DICOM) ---
    let sliceRotationDeg = 0;
    let sliceFlipV = false;
    let sliceFlipH = false;
    let currentSlicesList = [];
    let currentSliceJobId = null;

    // État du Modal Visionneuse Loupe
    let modalActiveIndex = 0;
    let modalZoomScale = 1.0;
    let modalPanX = 0;
    let modalPanY = 0;
    let modalIsDragging = false;
    let modalDragStartX = 0;
    let modalDragStartY = 0;

    function getSliceTransformString() {
        return `rotate(${sliceRotationDeg}deg) scale(${sliceFlipH ? -1 : 1}, ${sliceFlipV ? -1 : 1})`;
    }

    function updateSliceGalleryTransforms() {
        const transformStr = getSliceTransformString();
        document.querySelectorAll('#sliceGallery .slice-item img').forEach(img => {
            img.style.transform = transformStr;
        });

        const lblActiveOrientation = document.getElementById('lblActiveOrientation');
        if (lblActiveOrientation) {
            let parts = [];
            const deg = (sliceRotationDeg % 360 + 360) % 360;
            if (deg !== 0) parts.push(`${deg}°`);
            if (sliceFlipV) parts.push(`Inversion Axiale Haut/Bas`);
            if (sliceFlipH) parts.push(`Miroir D/G`);
            lblActiveOrientation.textContent = parts.length > 0 ? parts.join(' • ') : `0° (Normale radiologique)`;
        }
    }

    function updateCompassMarkers() {
        const topEl = document.getElementById('compassTop');
        const bottomEl = document.getElementById('compassBottom');
        const leftEl = document.getElementById('compassLeft');
        const rightEl = document.getElementById('compassRight');

        if (!topEl || !bottomEl || !leftEl || !rightEl) return;

        // Base : Haut = A (Antérieur), Bas = P (Postérieur), Gauche = D (Droit), Droite = G (Gauche)
        let top = 'A (Antérieur)';
        let bottom = 'P (Postérieur)';
        let left = 'D (Droit)';
        let right = 'G (Gauche)';

        if (sliceFlipV) {
            [top, bottom] = [bottom, top];
        }
        if (sliceFlipH) {
            [left, right] = [right, left];
        }

        const deg = (sliceRotationDeg % 360 + 360) % 360;
        if (deg === 90) {
            const oldTop = top, oldRight = right, oldBottom = bottom, oldLeft = left;
            top = oldLeft;
            right = oldTop;
            bottom = oldRight;
            left = oldBottom;
        } else if (deg === 180) {
            [top, bottom] = [bottom, top];
            [left, right] = [right, left];
        } else if (deg === 270) {
            const oldTop = top, oldRight = right, oldBottom = bottom, oldLeft = left;
            top = oldRight;
            left = oldTop;
            bottom = oldLeft;
            right = oldBottom;
        }

        topEl.textContent = top;
        bottomEl.textContent = bottom;
        leftEl.textContent = left;
        rightEl.textContent = right;
    }

    // Initialisation des écouteurs de la barre d'outils des coupes
    function setupSliceToolbar() {
        document.getElementById('btnRotateSliceCW')?.addEventListener('click', () => {
            sliceRotationDeg = (sliceRotationDeg + 90) % 360;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });

        document.getElementById('btnRotateSliceCCW')?.addEventListener('click', () => {
            sliceRotationDeg = (sliceRotationDeg - 90 + 360) % 360;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });

        document.getElementById('btnFlipSliceV')?.addEventListener('click', () => {
            sliceFlipV = !sliceFlipV;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });

        document.getElementById('btnFlipSliceH')?.addEventListener('click', () => {
            sliceFlipH = !sliceFlipH;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });

        document.getElementById('btnResetSliceOrientation')?.addEventListener('click', () => {
            sliceRotationDeg = 0;
            sliceFlipV = false;
            sliceFlipH = false;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });

        document.getElementById('btnSaveSliceOrientation')?.addEventListener('click', async () => {
            if (!currentJobId) {
                alert("Aucune analyse active.");
                return;
            }

            const btn = document.getElementById('btnSaveSliceOrientation');
            const origText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `⏳ Sauvegarde...`;

            try {
                const res = await fetch(`/api/job/${currentJobId}/rotate-slices`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'custom',
                        angle: sliceRotationDeg,
                        flip_v: sliceFlipV,
                        flip_h: sliceFlipH
                    })
                });

                if (!res.ok) throw new Error("Erreur de sauvegarde de l'orientation.");
                const data = await res.json();

                // Réinitialiser les transformations CSS puisque l'image est maintenant réorientée sur disque
                sliceRotationDeg = 0;
                sliceFlipV = false;
                sliceFlipH = false;
                updateSliceGalleryTransforms();

                // Forcer le rechargement des images dans la galerie et le modal avec cache buster
                const cacheBuster = `?t=${data.timestamp || Date.now()}`;
                document.querySelectorAll('#sliceGallery .slice-item img').forEach(img => {
                    const srcBase = img.src.split('?')[0];
                    img.src = srcBase + cacheBuster;
                });

                const modalImg = document.getElementById('modalSliceImg');
                if (modalImg && modalImg.src) {
                    const srcBase = modalImg.src.split('?')[0];
                    modalImg.src = srcBase + cacheBuster;
                }

                btn.innerHTML = `✓ Enregistré !`;
                setTimeout(() => {
                    btn.innerHTML = origText;
                    btn.disabled = false;
                }, 2000);
            } catch (err) {
                alert(`Erreur : ${err.message}`);
                btn.innerHTML = origText;
                btn.disabled = false;
            }
        });

        setupSliceModalEvents();
    }

    // Galerie des coupes axiales
    function renderSliceGallery(jobId, slices) {
        currentSliceJobId = jobId;
        currentSlicesList = slices || [];
        sliceGallery.innerHTML = '';

        if (!slices || slices.length === 0) {
            sliceGallery.innerHTML = `<div style="grid-column:1/-1;color:var(--text-dim);padding:2rem;text-align:center;">Aucun aperçu de coupe disponible.</div>`;
            return;
        }

        slices.forEach((sl, idx) => {
            const item = document.createElement('div');
            item.className = 'slice-item';
            item.style.cursor = 'pointer';
            item.title = `Cliquer pour agrandir la Coupe ${sl.label} (Z: ${sl.slice_index})`;
            item.innerHTML = `
                <div style="overflow:hidden;background:#000;display:flex;align-items:center;justify-content:center;position:relative;">
                    <img class="slice-item-img" src="/api/files/${jobId}/${sl.filename}" alt="${sl.label}" style="transform:${getSliceTransformString()};">
                    <span style="position:absolute;top:6px;right:6px;background:rgba(15,23,42,0.85);color:#38bdf8;padding:2px 6px;border-radius:3px;font-size:0.68rem;font-weight:700;">🔍 Agrandir</span>
                </div>
                <div class="slice-label">Coupe ${sl.label} (Z: ${sl.slice_index})</div>
            `;

            item.addEventListener('click', () => {
                openSliceModal(idx);
            });

            sliceGallery.appendChild(item);
        });

        updateSliceGalleryTransforms();
    }

    // Modal Visionneuse de Coupes Agrandie
    function openSliceModal(index) {
        if (!currentSlicesList || currentSlicesList.length === 0) return;
        modalActiveIndex = (index + currentSlicesList.length) % currentSlicesList.length;

        const sl = currentSlicesList[modalActiveIndex];
        const modal = document.getElementById('sliceViewerModal');
        const modalImg = document.getElementById('modalSliceImg');
        const modalTitle = document.getElementById('sliceModalTitle');
        const modalSub = document.getElementById('sliceModalSub');

        if (modalTitle) modalTitle.textContent = `Coupe Axiale ${sl.label} • Index Z: ${sl.slice_index}`;
        if (modalSub) modalSub.textContent = `Fichier: ${sl.filename} • Fenêtrage Abdominal (Centre: 40 HU, Largeur: 400 HU)`;
        
        modalZoomScale = 1.0;
        modalPanX = 0;
        modalPanY = 0;

        if (modalImg) {
            modalImg.src = `/api/files/${currentSliceJobId}/${sl.filename}`;
        }

        updateModalViewTransform();
        if (modal) modal.style.display = 'flex';
    }

    function closeSliceModal() {
        const modal = document.getElementById('sliceViewerModal');
        if (modal) modal.style.display = 'none';
    }

    function updateModalViewTransform() {
        const wrapper = document.getElementById('sliceCanvasWrapper');
        if (wrapper) {
            wrapper.style.transform = `translate(${modalPanX}px, ${modalPanY}px) scale(${modalZoomScale}) rotate(${sliceRotationDeg}deg) scale(${sliceFlipH ? -1 : 1}, ${sliceFlipV ? -1 : 1})`;
        }
        updateCompassMarkers();
    }

    function setupSliceModalEvents() {
        const modal = document.getElementById('sliceViewerModal');
        const backdrop = document.getElementById('sliceModalBackdrop');
        const btnClose = document.getElementById('modalBtnClose');
        const btnPrev = document.getElementById('modalBtnPrev');
        const btnNext = document.getElementById('modalBtnNext');
        const viewport = document.getElementById('sliceModalViewport');

        backdrop?.addEventListener('click', closeSliceModal);
        btnClose?.addEventListener('click', closeSliceModal);

        btnPrev?.addEventListener('click', () => {
            if (currentSlicesList.length > 0) {
                openSliceModal(modalActiveIndex - 1);
            }
        });

        btnNext?.addEventListener('click', () => {
            if (currentSlicesList.length > 0) {
                openSliceModal(modalActiveIndex + 1);
            }
        });

        // Zoom boutons
        document.getElementById('modalBtnZoomIn')?.addEventListener('click', () => {
            modalZoomScale = Math.min(modalZoomScale * 1.25, 4.0);
            updateModalViewTransform();
        });
        document.getElementById('modalBtnZoomOut')?.addEventListener('click', () => {
            modalZoomScale = Math.max(modalZoomScale / 1.25, 0.5);
            updateModalViewTransform();
        });
        document.getElementById('modalBtnZoomReset')?.addEventListener('click', () => {
            modalZoomScale = 1.0;
            modalPanX = 0;
            modalPanY = 0;
            updateModalViewTransform();
        });

        // Rotation boutons dans le modal
        document.getElementById('modalBtnRotateCW')?.addEventListener('click', () => {
            sliceRotationDeg = (sliceRotationDeg + 90) % 360;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });
        document.getElementById('modalBtnRotateCCW')?.addEventListener('click', () => {
            sliceRotationDeg = (sliceRotationDeg - 90 + 360) % 360;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });
        document.getElementById('modalBtnFlipV')?.addEventListener('click', () => {
            sliceFlipV = !sliceFlipV;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });
        document.getElementById('modalBtnFlipH')?.addEventListener('click', () => {
            sliceFlipH = !sliceFlipH;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });
        document.getElementById('modalBtnReset')?.addEventListener('click', () => {
            sliceRotationDeg = 0;
            sliceFlipV = false;
            sliceFlipH = false;
            modalZoomScale = 1.0;
            modalPanX = 0;
            modalPanY = 0;
            updateSliceGalleryTransforms();
            updateModalViewTransform();
        });

        // Téléchargement de l'image orientée
        document.getElementById('modalBtnDownload')?.addEventListener('click', () => {
            const sl = currentSlicesList[modalActiveIndex];
            const modalImg = document.getElementById('modalSliceImg');
            if (!sl || !modalImg) return;

            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            const w = modalImg.naturalWidth || 512;
            const h = modalImg.naturalHeight || 512;
            canvas.width = w;
            canvas.height = h;

            ctx.save();
            ctx.translate(w / 2, h / 2);
            ctx.rotate((sliceRotationDeg * Math.PI) / 180);
            ctx.scale(sliceFlipH ? -1 : 1, sliceFlipV ? -1 : 1);
            ctx.drawImage(modalImg, -w / 2, -h / 2, w, h);
            ctx.restore();

            const link = document.createElement('a');
            link.download = `coupe_${sl.label.toLowerCase()}_orientee.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        });

        // Navigation clavier & raccourcis
        window.addEventListener('keydown', (e) => {
            if (!modal || modal.style.display !== 'flex') return;
            if (e.key === 'Escape') closeSliceModal();
            else if (e.key === 'ArrowLeft') openSliceModal(modalActiveIndex - 1);
            else if (e.key === 'ArrowRight') openSliceModal(modalActiveIndex + 1);
            else if (e.key === 'r' || e.key === 'R') {
                sliceRotationDeg = (sliceRotationDeg + 90) % 360;
                updateSliceGalleryTransforms();
                updateModalViewTransform();
            } else if (e.key === 'v' || e.key === 'V') {
                sliceFlipV = !sliceFlipV;
                updateSliceGalleryTransforms();
                updateModalViewTransform();
            } else if (e.key === 'h' || e.key === 'H') {
                sliceFlipH = !sliceFlipH;
                updateSliceGalleryTransforms();
                updateModalViewTransform();
            }
        });

        // Zoom à la molette sur le viewport
        viewport?.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 1.15 : 0.85;
            modalZoomScale = Math.max(0.4, Math.min(5.0, modalZoomScale * delta));
            updateModalViewTransform();
        }, { passive: false });

        // Pan par glisser-déposer sur le viewport
        viewport?.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            modalIsDragging = true;
            modalDragStartX = e.clientX - modalPanX;
            modalDragStartY = e.clientY - modalPanY;
            viewport.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', (e) => {
            if (!modalIsDragging) return;
            modalPanX = e.clientX - modalDragStartX;
            modalPanY = e.clientY - modalDragStartY;
            updateModalViewTransform();
        });

        window.addEventListener('mouseup', () => {
            if (modalIsDragging) {
                modalIsDragging = false;
                if (viewport) viewport.style.cursor = 'default';
            }
        });
    }

    // Tableaux de métadonnées
    function renderMetadataTables(result) {
        if (!result) return;
        const p = result.patient_info || {};
        patientDetailsTable.innerHTML = `
            <tr><th>Nom du Patient</th><td>${p.patient_name || 'Anonyme'}</td></tr>
            <tr><th>Identifiant (ID)</th><td>${p.patient_id || '--'}</td></tr>
            <tr><th>Date de l'examen</th><td>${p.study_date || '--'}</td></tr>
            <tr><th>Sexe / Âge</th><td>${p.patient_sex || '--'} / ${p.patient_age || '--'}</td></tr>
            <tr><th>Modalité</th><td>${p.modality || 'CT (Scanner)'}</td></tr>
        `;

        const acq = result.acquisition_info || {};
        const spacingStr = acq.spacing_mm ? acq.spacing_mm.join(' × ') + ' mm' : '--';
        acquisitionDetailsTable.innerHTML = `
            <tr><th>Épaisseur de coupe</th><td>${acq.slice_thickness_mm ? acq.slice_thickness_mm + ' mm' : '--'}</td></tr>
            <tr><th>Espacement Voxel (X×Y×Z)</th><td>${spacingStr}</td></tr>
            <tr><th>Nombre total de coupes</th><td>${acq.total_slices || '--'}</td></tr>
            <tr><th>Constructeur / Modèle</th><td>${p.manufacturer || ''} ${p.model_name || ''}</td></tr>
            <tr><th>Tension tube (kVp)</th><td>${p.kvp ? p.kvp + ' kV' : '--'}</td></tr>
        `;
    }

    // --- Historique des Analyses ---
    async function loadHistory() {
        try {
            const res = await fetch('/api/history');
            const data = await res.json();
            const history = data.history || [];

            historyTableBody.innerHTML = '';
            if (history.length === 0) {
                historyTableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:2rem;">Aucune analyse enregistrée.</td></tr>`;
                return;
            }

            history.forEach(item => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${item.patient_name}</strong></td>
                    <td>${item.patient_id || '--'}</td>
                    <td>${item.timestamp}</td>
                    <td><span class="badge ${item.fast_mode ? 'badge-warning' : 'badge-success'}">${item.fast_mode ? 'Rapide (3mm)' : 'HD (1.5mm)'}</span></td>
                    <td><strong>${item.liver_volume_cm3 ? item.liver_volume_cm3.toLocaleString('fr-FR') + ' cm³' : '--'}</strong></td>
                    <td>${item.elapsed_seconds ? item.elapsed_seconds + ' s' : '--'}</td>
                    <td>
                        <div style="display: flex; gap: 0.35rem; justify-content: flex-end;">
                            <button class="btn btn-secondary btn-sm" onclick="window.viewHistoryJob('${item.job_id}')" title="Ouvrir la volumétrie 3D et le bilan">
                                📊 Ouvrir
                            </button>
                            <a class="btn btn-secondary btn-sm" href="/mpr-viewer/${item.job_id}" target="_blank" title="Ouvrir les reconstructions MPR & MIP dans une nouvelle fenêtre" style="border-color: #38bdf8; color: #38bdf8;">
                                🩻 MPR
                            </a>
                        </div>
                    </td>
                `;
                historyTableBody.appendChild(tr);
            });
        } catch (e) {
            console.error("Erreur chargement historique :", e);
        }
    }

    window.viewHistoryJob = (jobId) => {
        fetchAndDisplayResults(jobId);
    };

    // Initialisation de la barre d'outils et du modal de rotation des coupes
    setupSliceToolbar();

    // Chargement initial de l'historique
    loadHistory();
});

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py
------
Serveur Web FastAPI pour la plateforme moderne de Volumétrie Hépatique.
Permet de piloter 3D Slicer et TotalSegmentator en arrière-plan, de streamer les logs en direct,
de visualiser le modèle 3D du foie et d'exporter des comptes-rendus cliniques.
"""

import os
import sys
import json
import time
import uuid
import shutil
import asyncio
import subprocess
import threading
import traceback
import struct
from datetime import datetime
from typing import Dict, Any, Optional, List
import io
import numpy as np
from PIL import Image

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Chemins de base du projet
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
WORKER_SCRIPT = os.path.join(BASE_DIR, "slicer_worker.py")
ERROR_LOG_PATH = os.path.join(BASE_DIR, "server_error.log")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Initialisation de l'application avec debug=True pour diagnostics précis
app = FastAPI(title="HepaVol - Volumétrie Hépatique IA", version="2.0.0", debug=True)

# Gestionnaire global des exceptions pour capturer et logger tout problème
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    err_tb = traceback.format_exc()
    log_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERREUR 500 sur {request.method} {request.url.path} :\n{err_tb}\n"
    print("\n" + "=" * 60, flush=True)
    print(log_line, flush=True)
    print("=" * 60 + "\n", flush=True)
    try:
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as ef:
            ef.write(log_line)
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Erreur serveur interne : {str(exc)}",
            "error_type": type(exc).__name__,
            "path": request.url.path,
            "traceback": err_tb
        }
    )

# Montage des fichiers statiques
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Initialisation des templates Jinja2 (rapport médical A4 et visualiseur MPR)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Détection de l'exécutable 3D Slicer
DEFAULT_SLICER_PATHS = [
    "/Applications/Slicer.app/Contents/MacOS/Slicer",
    os.path.expanduser("~/Applications/Slicer.app/Contents/MacOS/Slicer"),
    "/Applications/3D Slicer.app/Contents/MacOS/Slicer",
    "/Applications/Slicer-5.8.0.app/Contents/MacOS/Slicer",
]


def detect_slicer_path() -> Optional[str]:
    """Détecte l'exécutable Slicer installé sur le Mac."""
    custom_path = os.environ.get("SLICER_PATH")
    if custom_path and os.path.exists(custom_path):
        return custom_path

    for path in DEFAULT_SLICER_PATHS:
        if os.path.exists(path):
            return path
    return None


SLICER_EXE = detect_slicer_path()

# Gestion des tâches en cours (en mémoire et persisté sur disque)
active_jobs: Dict[str, Dict[str, Any]] = {}
job_locks: Dict[str, threading.Lock] = {}


class AnalysisRequest(BaseModel):
    input_path: str
    portal_path: Optional[str] = None
    arterial_path: Optional[str] = None
    use_fast: bool = False
    target_organs: List[str] = ["liver"]
    segmentation_task: Optional[str] = "liver_segments"
    reconstruct_vessels: Optional[bool] = False
    patient_weight: Optional[float] = None
    patient_height: Optional[float] = None
    patient_sex: Optional[str] = "M"


class PickFolderRequest(BaseModel):
    prompt: Optional[str] = None


class ValidatePathRequest(BaseModel):
    path: str


class LocateFolderRequest(BaseModel):
    name: str


def run_slicer_process(job_id: str, config_path: str, job_output_dir: str):
    """Exécute 3D Slicer en arrière-plan et capture la progression."""
    global SLICER_EXE
    job = active_jobs.get(job_id)
    if not job:
        return

    slicer_bin = SLICER_EXE or detect_slicer_path()
    if not slicer_bin:
        job["status"] = "error"
        job["error"] = "Exécutable 3D Slicer introuvable sur la machine (/Applications/Slicer.app)."
        job["progress"] = 0
        return

    log_file_path = os.path.join(job_output_dir, "execution.log")

    cmd = [
        slicer_bin,
        "--no-splash",
        "--no-main-window",
        "--python-script",
        WORKER_SCRIPT,
        config_path
    ]

    job["status"] = "running"
    job["progress"] = 5
    job["current_step"] = "Démarrage de 3D Slicer..."
    start_time = time.time()

    try:
        ret_code = 0
        try:
            with open(log_file_path, "w", encoding="utf-8") as log_f:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=BASE_DIR
                )
                job["process"] = process

                try:
                    for line in iter(process.stdout.readline, ''):
                        if not line:
                            break
                        line_str = line.strip()
                        try:
                            log_f.write(line)
                            log_f.flush()
                        except (OSError, IOError):
                            pass

                        # Ajout dans la mémoire tampon pour SSE
                        job["logs"].append(line_str)
                        if len(job["logs"]) > 500:
                            job["logs"].pop(0)

                        # Parsing de la progression
                        if "[PROGRESS " in line_str:
                            try:
                                p_part = line_str.split("[PROGRESS ")[1]
                                percent_str, msg = p_part.split("]", 1)
                                pct = int(percent_str.strip())
                                job["progress"] = pct
                                job["current_step"] = msg.strip()
                            except Exception:
                                pass
                        elif "[INFO]" in line_str:
                            job["last_info"] = line_str.replace("[INFO]", "").strip()
                except (OSError, IOError, ValueError) as stream_err:
                    job["logs"].append(f"[INFO] Flux de log standard finalisé ({stream_err}). Attente de Slicer...")

                try:
                    process.wait(timeout=1800)
                    ret_code = process.returncode
                except Exception:
                    ret_code = process.poll() if process.poll() is not None else 0
        except Exception as spawn_err:
            ret_code = -1
            job["logs"].append(f"[ERROR] Erreur exécution Slicer : {spawn_err}")

        # Attente brève de la synchronisation du fichier result.json sur le disque
        result_json_path = os.path.join(job_output_dir, "result.json")
        for _ in range(12):
            if os.path.exists(result_json_path):
                break
            time.sleep(0.5)

        # Vérification prioritaire du résultat sur disque
        if os.path.exists(result_json_path):
            try:
                with open(result_json_path, "r", encoding="utf-8") as rf:
                    result_data = json.load(rf)
                
                if result_data.get("status") == "success":
                    job["status"] = "completed"
                    job["progress"] = 100
                    job["current_step"] = "Volumétrie terminée avec succès !"
                    job["result"] = result_data
                    job["elapsed_seconds"] = result_data.get("elapsed_seconds") or round(time.time() - start_time, 1)
                    job["error"] = None
                    return
                else:
                    job["status"] = "error"
                    job["current_step"] = "Erreur pendant le traitement."
                    job["error"] = result_data.get("error_message", f"Échec de l'analyse Slicer (code {ret_code})")
                    return
            except Exception as read_err:
                pass

        # Si result.json n'a pas pu être lu
        job["status"] = "error"
        job["current_step"] = "Erreur pendant le traitement."
        job["error"] = f"Échec de l'exécution de Slicer (Code {ret_code}). Consultez le journal pour plus de détails."

    except Exception as exc:
        result_json_path = os.path.join(job_output_dir, "result.json")
        if os.path.exists(result_json_path):
            try:
                with open(result_json_path, "r", encoding="utf-8") as rf:
                    result_data = json.load(rf)
                if result_data.get("status") == "success":
                    job["status"] = "completed"
                    job["progress"] = 100
                    job["current_step"] = "Volumétrie terminée avec succès !"
                    job["result"] = result_data
                    job["elapsed_seconds"] = result_data.get("elapsed_seconds") or round(time.time() - start_time, 1)
                    job["error"] = None
                    return
            except Exception:
                pass
        job["status"] = "error"
        job["error"] = str(exc)
        job["current_step"] = f"Erreur système : {exc}"
    finally:
        job["process"] = None


@app.get("/", response_class=FileResponse)
async def serve_index():
    """
    Page d'accueil de l'application.
    Servie directement sous forme de FileResponse statique pour une fiabilité absolue
    (aucune dépendance à Jinja2 ou à la version de Starlette).
    """
    index_file = os.path.join(TEMPLATES_DIR, "index.html")
    if not os.path.exists(index_file):
        raise HTTPException(status_code=404, detail="Fichier index.html introuvable.")
    return FileResponse(index_file, media_type="text/html")


@app.get("/api/system-status")
async def get_system_status():
    """Vérifie l'état de l'environnement (Slicer, TotalSegmentator, etc.)."""
    global SLICER_EXE
    if not SLICER_EXE:
        SLICER_EXE = detect_slicer_path()

    return {
        "slicer_installed": SLICER_EXE is not None,
        "slicer_path": SLICER_EXE or "Introuvable (/Applications/Slicer.app)",
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "output_directory": OUTPUT_DIR,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def _run_osascript_pick_folder(prompt: Optional[str] = None):
    """Fonction synchrone exécutée dans un thread pour ne pas bloquer l'event loop.
    Active le Finder pour faire surgir immédiatement la fenêtre de sélection en premier plan
    sur macOS sans nécessiter de cliquer sur l'icône du Terminal dans le Dock.
    """
    p_text = prompt or "Sélectionnez le dossier contenant les images DICOM du scanner"
    safe_prompt = p_text.replace('"', '\\"')
    apple_script = f'''
set frontApp to ""
try
    tell application "System Events" to set frontApp to name of first application process whose frontmost is true
end try

try
    tell application "Finder" to activate
end try

set chosenFolder to ""
try
    set chosenFolder to (choose folder with prompt "{safe_prompt}")
on error errMsg number errNum
    if frontApp is not "" then
        try
            tell application frontApp to activate
        end try
    end if
    error errMsg number errNum
end try

if frontApp is not "" then
    try
        tell application frontApp to activate
    end try
end if

return POSIX path of chosenFolder
'''
    try:
        res = subprocess.run(["osascript", "-e", apple_script], capture_output=True, text=True, timeout=180)
        if res.returncode == 0:
            folder_path = res.stdout.strip()
            if folder_path:
                dicom_count = 0
                for root, _, files in os.walk(folder_path):
                    for f in files:
                        if not f.startswith("."):
                            dicom_count += 1
                return {
                    "success": True,
                    "path": folder_path,
                    "files_count": dicom_count
                }
        return {"success": False, "cancelled": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/pick-folder")
async def pick_folder(req: Optional[PickFolderRequest] = None):
    """
    Ouvre la boîte de dialogue native macOS de sélection de dossier (dans un thread non bloquant).
    """
    prompt = req.prompt if req else None
    return await asyncio.to_thread(_run_osascript_pick_folder, prompt)


def parse_dicom_basic(file_path: str) -> dict:
    """
    Parseur DICOM ultra-léger en pur Python sans dépendances tierces (inspiré des outils de qq284397146-cpu, 2026).
    Extrait les coordonnées Z réelles, le pas de coupe, le libellé de série et les coefficients Hounsfield (HU).
    """
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        return {"valid_dicom": False}
    try:
        with open(file_path, "rb") as f:
            f.seek(128)
            magic = f.read(4)
            if magic != b"DICM":
                return {"valid_dicom": False}
            
            info = {
                "valid_dicom": True,
                "rows": 512,
                "columns": 512,
                "rescale_intercept": 0.0,
                "rescale_slope": 1.0,
                "spacing": [0.7, 0.7, 1.5]
            }
            while True:
                tag_bytes = f.read(4)
                if len(tag_bytes) < 4:
                    break
                group, elem = struct.unpack("<HH", tag_bytes)
                pos = f.tell()
                vr = f.read(2)
                if vr in [b"OB", b"OW", b"OF", b"SQ", b"UT", b"UN"]:
                    f.read(2)
                    length = struct.unpack("<I", f.read(4))[0]
                elif vr in [b"AE", b"AS", b"AT", b"CS", b"DA", b"DS", b"DT", b"FL", b"FD", b"IS", b"LO", b"LT", b"PN", b"SH", b"SL", b"SS", b"ST", b"TM", b"UI", b"UL", b"US"]:
                    length = struct.unpack("<H", f.read(2))[0]
                else:
                    f.seek(pos)
                    length = struct.unpack("<I", f.read(4))[0]
                    vr = b"??"
                
                if length == 0xFFFFFFFF or length > 50000000:
                    break
                
                val_bytes = f.read(length)
                
                if (group, elem) == (0x0008, 0x103E): # Series Description
                    info["series_description"] = val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00")
                elif (group, elem) == (0x0020, 0x0013): # Instance Number
                    try:
                        info["instance_number"] = int(val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00"))
                    except Exception:
                        pass
                elif (group, elem) == (0x0020, 0x0032): # Image Position (Patient)
                    pos_str = val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00")
                    parts = pos_str.split("\\")
                    if len(parts) >= 3:
                        try:
                            info["z_pos"] = float(parts[2])
                        except Exception:
                            pass
                elif (group, elem) == (0x0018, 0x0050): # Slice Thickness
                    try:
                        info["slice_thickness"] = float(val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00"))
                    except Exception:
                        pass
                elif (group, elem) == (0x0028, 0x0010): # Rows
                    info["rows"] = struct.unpack("<H", val_bytes)[0] if len(val_bytes) >= 2 else 512
                elif (group, elem) == (0x0028, 0x0011): # Columns
                    info["columns"] = struct.unpack("<H", val_bytes)[0] if len(val_bytes) >= 2 else 512
                elif (group, elem) == (0x0028, 0x1052): # Rescale Intercept
                    try:
                        info["rescale_intercept"] = float(val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00"))
                    except Exception:
                        pass
                elif (group, elem) == (0x0028, 0x1053): # Rescale Slope
                    try:
                        info["rescale_slope"] = float(val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00"))
                    except Exception:
                        pass
                elif (group, elem) == (0x0028, 0x0030): # Pixel Spacing
                    sp_str = val_bytes.decode("latin1", errors="ignore").strip().rstrip("\x00")
                    parts = sp_str.split("\\")
                    if len(parts) >= 2:
                        try:
                            info["pixel_spacing"] = [float(parts[0]), float(parts[1])]
                        except Exception:
                            pass
                elif (group, elem) == (0x7FE0, 0x0010): # Pixel Data
                    info["pixel_data_offset"] = f.tell() - length
                    break
            
            s_desc = (info.get("series_description") or "").lower()
            if any(w in s_desc for w in ("art", "a.", "early", "arteriel", "arterielle")):
                info["detected_phase"] = "artérielle"
            elif any(w in s_desc for w in ("port", "pv", "parench", "tardif", "portal", "vein")):
                info["detected_phase"] = "portale"
            else:
                info["detected_phase"] = "inconnue"
                
            return info
    except Exception:
        return {"valid_dicom": False}


@app.post("/api/validate-path")
async def validate_path(req: ValidatePathRequest):
    """Vérifie l'existence, la validité et introspecte les métadonnées DICOM d'un chemin."""
    path = os.path.expanduser(req.path.strip())
    if not os.path.exists(path):
        return {"valid": False, "message": "Le chemin spécifié n'existe pas."}

    is_dir = os.path.isdir(path)
    file_count = 0
    volume_file = False
    dicom_meta = None

    if is_dir:
        for root, _, files in os.walk(path):
            for f in files:
                if not f.startswith("."):
                    file_count += 1
                    fl = f.lower()
                    if fl.endswith(('.nii', '.nii.gz', '.nrrd', '.mha')):
                        volume_file = True
                    elif dicom_meta is None and (fl.endswith(".dcm") or "." not in f):
                        try:
                            parsed = parse_dicom_basic(os.path.join(root, f))
                            if parsed.get("valid_dicom"):
                                dicom_meta = {
                                    "series_description": parsed.get("series_description", "Non spécifié"),
                                    "detected_phase": parsed.get("detected_phase", "inconnue"),
                                    "slice_thickness": parsed.get("slice_thickness"),
                                    "pixel_spacing": parsed.get("pixel_spacing")
                                }
                        except Exception:
                            pass
    else:
        file_count = 1
        volume_file = path.lower().endswith(('.nii', '.nii.gz', '.nrrd', '.mha', '.dcm'))
        if path.lower().endswith(".dcm") or "." not in os.path.basename(path):
            parsed = parse_dicom_basic(path)
            if parsed.get("valid_dicom"):
                dicom_meta = {
                    "series_description": parsed.get("series_description", "Non spécifié"),
                    "detected_phase": parsed.get("detected_phase", "inconnue"),
                    "slice_thickness": parsed.get("slice_thickness"),
                    "pixel_spacing": parsed.get("pixel_spacing")
                }

    msg = f"Dossier valide ({file_count} fichiers détectés"
    if dicom_meta and dicom_meta.get("series_description"):
        msg += f" • Série : {dicom_meta['series_description']}"
    msg += ")" if is_dir else "Fichier d'imagerie valide"

    return {
        "valid": True,
        "is_dir": is_dir,
        "files_count": file_count,
        "is_volume_file": volume_file,
        "dicom_meta": dicom_meta,
        "message": msg
    }


@app.post("/api/locate-folder")
async def locate_folder(req: LocateFolderRequest):
    """
    Tente de localiser un dossier ou fichier par son nom parmi les emplacements
    habituels de macOS (Téléchargements, Bureau, Documents, Volumes externes).
    Permet un glisser-déposer instantané sans duplication de fichiers.
    """
    raw_name = req.name.strip().strip("/")
    if not raw_name:
        return {"found": False}

    # Liste des racines de recherche standards
    search_roots = [
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        BASE_DIR,
    ]

    # Vérification des disques montés sous /Volumes
    if os.path.exists("/Volumes"):
        try:
            for v in os.listdir("/Volumes"):
                if not v.startswith(".") and not v.startswith("Recovery"):
                    v_path = os.path.join("/Volumes", v)
                    if os.path.isdir(v_path):
                        search_roots.append(v_path)
                        for sub in ("DICOM", "Dicom", "Scanner", "CT", "Images", "Scans"):
                            sub_p = os.path.join(v_path, sub)
                            if os.path.isdir(sub_p):
                                search_roots.append(sub_p)
        except Exception:
            pass

    # 1. Vérification directe dans chaque racine
    for root in search_roots:
        cand = os.path.join(root, raw_name)
        if os.path.exists(cand):
            if os.path.isdir(cand):
                files_count = sum(len(f) for _, _, f in os.walk(cand) if not any(x.startswith(".") for x in f))
                if files_count > 0:
                    return {"found": True, "path": cand, "files_count": files_count}
            else:
                return {"found": True, "path": cand, "files_count": 1}

    # 2. Recherche rapide à 1 niveau de profondeur dans Téléchargements et Bureau
    for root in (os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")):
        if os.path.isdir(root):
            try:
                for sub in os.listdir(root):
                    sub_p = os.path.join(root, sub)
                    if os.path.isdir(sub_p) and not sub.startswith("."):
                        cand = os.path.join(sub_p, raw_name)
                        if os.path.exists(cand):
                            count = sum(len(f) for _, _, f in os.walk(cand) if not any(x.startswith(".") for x in f)) if os.path.isdir(cand) else 1
                            if count > 0:
                                return {"found": True, "path": cand, "files_count": count}
            except Exception:
                pass

    return {"found": False}


@app.post("/api/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    folder_name: str = Form("dicom_upload")
):
    """
    Réceptionne des fichiers DICOM ou volumes déposés par glisser-déposer.
    Stocke les fichiers dans le dossier uploads/ du serveur local.
    """
    safe_name = "".join(c for c in folder_name if c.isalnum() or c in ("-", "_", ".")).strip() or "dicom_upload"
    unique_dir = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    target_dir = os.path.join(UPLOAD_DIR, unique_dir)
    os.makedirs(target_dir, exist_ok=True)

    saved_count = 0
    saved_volume_path = None

    for f in files:
        if not f.filename or f.filename.startswith(".") or f.filename.endswith(".DS_Store"):
            continue
        base_name = os.path.basename(f.filename)
        dest_path = os.path.join(target_dir, base_name)
        try:
            with open(dest_path, "wb") as out_f:
                shutil.copyfileobj(f.file, out_f)
            saved_count += 1
            if base_name.lower().endswith(('.nii', '.nii.gz', '.nrrd', '.mha')):
                saved_volume_path = dest_path
        except Exception:
            continue
        finally:
            await f.close()

    if saved_count == 0:
        shutil.rmtree(target_dir, ignore_errors=True)
        return {"success": False, "error": "Aucun fichier valide n'a pu être enregistré."}

    final_path = saved_volume_path if (saved_count == 1 and saved_volume_path) else target_dir

    return {
        "success": True,
        "path": final_path,
        "files_count": saved_count,
        "message": f"{saved_count} fichier(s) réceptionné(s) avec succès."
    }


@app.post("/api/analyze")
async def start_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    """Démarre une nouvelle analyse volumétrique."""
    portal_input = req.portal_path or req.input_path
    expanded_path = os.path.expanduser(portal_input.strip())
    if not os.path.exists(expanded_path):
        raise HTTPException(status_code=400, detail=f"Le dossier de la phase portale n'existe pas : {portal_input}")

    expanded_arterial = None
    if req.arterial_path and req.arterial_path.strip():
        expanded_arterial = os.path.expanduser(req.arterial_path.strip())
        if not os.path.exists(expanded_arterial):
            raise HTTPException(status_code=400, detail=f"Le dossier de la phase artérielle n'existe pas : {req.arterial_path}")

    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)

    config_data = {
        "job_id": job_id,
        "input_path": expanded_path,
        "portal_path": expanded_path,
        "arterial_path": expanded_arterial,
        "output_dir": job_output_dir,
        "use_fast": req.use_fast,
        "target_organs": req.target_organs or ["liver"],
        "segmentation_task": req.segmentation_task or "liver_segments",
        "reconstruct_vessels": bool(req.reconstruct_vessels or ("vessels" in (req.target_organs or [])) or ("liver_vessels" in (req.target_organs or []))),
        "patient_weight": req.patient_weight,
        "patient_height": req.patient_height,
        "patient_sex": req.patient_sex or "M"
    }

    config_path = os.path.join(job_output_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    active_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "current_step": "En file d'attente...",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "logs": [],
        "output_dir": job_output_dir,
        "config": config_data,
        "result": None,
        "error": None,
        "process": None
    }

    # Lancement du traitement en tâche d'arrière-plan
    background_tasks.add_task(run_slicer_process, job_id, config_path, job_output_dir)

    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Analyse volumétrique lancée avec succès."
    }


def load_stl_vertices(stl_path: str):
    """Lit les sommets (vertices) 3D d'un fichier STL binaire."""
    if not os.path.exists(stl_path):
        return None
    try:
        with open(stl_path, "rb") as f:
            f.seek(80)
            nb_tri_b = f.read(4)
            if len(nb_tri_b) < 4:
                return None
            num_triangles = struct.unpack("<I", nb_tri_b)[0]
            data = f.read(num_triangles * 50)
        dtype = np.dtype([
            ('normal', '<f4', (3,)),
            ('vertices', '<f4', (3, 3)),
            ('attr', '<u2')
        ])
        triangles = np.frombuffer(data, dtype=dtype)
        vertices = triangles['vertices'].reshape(-1, 3)
        return vertices
    except Exception:
        return None


def compute_surgical_margins(job_dir: str):
    """
    Calcule les marges chirurgicales 3D minimales (en mm) entre la tumeur et les structures vasculaires/capsulaires.
    Implémente les métriques de distance de sécurité et le statut R0/R1 (inspiré de rmsandu/segmentation-eval, août 2026).
    """
    tumour_stl = os.path.join(job_dir, "liver_tumour.stl")
    if not os.path.exists(tumour_stl):
        for f in os.listdir(job_dir):
            if f.lower().endswith(".stl") and any(w in f.lower() for w in ("tumour", "tumor", "tumeur", "lesion")):
                tumour_stl = os.path.join(job_dir, f)
                break
    if not os.path.exists(tumour_stl):
        return None

    t_v = load_stl_vertices(tumour_stl)
    if t_v is None or len(t_v) == 0:
        return None

    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(t_v)
    except Exception:
        return None

    targets = [
        ("portal_vein", ["portal_vein.stl", "veine_porte.stl"], "Veine Porte"),
        ("hepatic_vein", ["hepatic_vein.stl", "veines_hepatiques.stl", "sus_hepatiques.stl"], "Veines Sus-Hépatiques"),
        ("inferior_vena_cava", ["inferior_vena_cava.stl", "vci.stl", "veine_cave.stl"], "Veine Cave Inférieure"),
        ("hepatic_artery", ["hepatic_artery.stl", "artere_hepatique.stl", "artery.stl"], "Artère Hépatique"),
        ("liver_capsule", ["liver.stl", "foie.stl"], "Capsule Glissonienne")
    ]
    
    margins = {}
    min_overall_vascular = 999.0
    for key, cands, label in targets:
        matched_file = None
        for cand in cands:
            cand_p = os.path.join(job_dir, cand)
            if os.path.exists(cand_p):
                matched_file = cand_p
                break
        if matched_file:
            v_pts = load_stl_vertices(matched_file)
            if v_pts is not None and len(v_pts) > 0:
                dists, _ = tree.query(v_pts)
                d_min = round(float(np.min(dists)), 2)
                margins[key] = {
                    "label": label,
                    "distance_mm": d_min,
                    "file": os.path.basename(matched_file)
                }
                if key != "liver_capsule" and d_min < min_overall_vascular:
                    min_overall_vascular = d_min

    if min_overall_vascular >= 10.0:
        r0_status = "R0 Large (Sécurité optimale ≥ 10 mm)"
        r0_badge = "badge-success"
    elif min_overall_vascular >= 1.0:
        r0_status = "R0 Étroite (Marge limite 1-9 mm)"
        r0_badge = "badge-warning"
    else:
        r0_status = "Risque R1 / Contact Vasculaire (< 1 mm)"
        r0_badge = "badge-danger"

    return {
        "calculated": True,
        "margins": margins,
        "min_vascular_margin_mm": min_overall_vascular if min_overall_vascular < 900 else None,
        "r0_status": r0_status,
        "r0_badge": r0_badge,
        "reference": "rmsandu (segmentation-eval 2026), Nath & Saha (2026)"
    }


def ensure_3d_segments(job_dir: str, result_data: dict) -> bool:
    """
    Garantit la présence de segments_3d dans model_3d si les fichiers STL individuels sont présents sur le disque.
    Permet à l'utilisateur de masquer/afficher chaque segment indépendamment en 3D.
    """
    if not result_data or not os.path.isdir(job_dir):
        return False
    
    model_3d = result_data.setdefault("model_3d", {})
    all_files = os.listdir(job_dir)
    segments_3d = []
    
    # 1. Segments de Couinaud
    if not (model_3d.get("has_segments") and model_3d.get("segments") and len(model_3d["segments"]) > 0):
        couinaud = result_data.get("couinaud_segments") or result_data.get("liver", {}).get("couinaud_segments", {})
        if couinaud:
            for k in range(1, 9):
                seg_key = f"liver_segment_{k}"
                s_data = couinaud.get(seg_key)
                if not s_data:
                    continue
                
                matched_file = None
                for fname in all_files:
                    if fname.lower().endswith(".stl") and fname.lower() != "liver.stl":
                        fl = fname.lower()
                        if f"segment_{k}." in fl or f"segment_{k}_" in fl or f"segment_{k}" in fl:
                            matched_file = fname
                            break
                
                if matched_file:
                    segments_3d.append({
                        "id": seg_key,
                        "number": s_data.get("couinaud_number", f"{k}"),
                        "name": s_data.get("couinaud_label", f"Segment {k}"),
                        "subname": s_data.get("anatomical_description", ""),
                        "lobe": s_data.get("lobe", "Foie"),
                        "filename": matched_file,
                        "color_hex": s_data.get("color_hex", "#38bdf8"),
                        "color_rgb": s_data.get("color_rgb", [56, 189, 248]),
                        "volume_cm3": s_data.get("volume_cm3", 0.0),
                        "pct_of_liver": s_data.get("pct_of_liver", 0.0)
                    })

    # Détection des structures vasculaires, biliaires et tumorales 3D
    vessel_configs = [
        ("portal_vein", ["portal_vein.stl", "veine_porte.stl"], "Veine Porte", "Système porte afférent et branches segmentaires", "#38bdf8", [56, 189, 248]),
        ("hepatic_vein", ["hepatic_vein.stl", "veines_hepatiques.stl", "sus_hepatiques.stl"], "Veines Sus-Hépatiques", "Veines hépatiques droite, médiane et gauche", "#2563eb", [37, 99, 235]),
        ("inferior_vena_cava", ["inferior_vena_cava.stl", "vci.stl", "veine_cave.stl"], "Veine Cave Inférieure", "Axe rétro-hépatique collecteur", "#1e3a8a", [30, 58, 138]),
        ("hepatic_artery", ["hepatic_artery.stl", "artere_hepatique.stl", "artery.stl"], "Artère Hépatique", "Flux artériel hépatique et branches hilaires", "#ef4444", [239, 68, 68]),
        ("gallbladder", ["gallbladder.stl", "vesicule_biliaire.stl", "vesicule.stl"], "Vésicule Biliaire", "Réservoir cystique et voies biliaires", "#10b981", [16, 185, 129]),
        ("liver_tumour", ["liver_tumour.stl", "liver_tumor.stl", "tumeur.stl", "lesion.stl"], "Lésions / Tumeurs", "Lésion focale intra-hépatique (Charge tumorale)", "#f59e0b", [245, 158, 11])
    ]
    vessels_3d = []
    for v_id, candidate_names, v_name, v_sub, color_hex, color_rgb in vessel_configs:
        matched = None
        for cand in candidate_names:
            if cand in all_files:
                matched = cand
                break
        if not matched:
            for fname in all_files:
                fl = fname.lower()
                if fl.endswith(".stl") and any(c.replace(".stl", "") in fl for c in candidate_names):
                    matched = fname
                    break
        if matched:
            vessels_3d.append({
                "id": v_id,
                "name": v_name,
                "subname": v_sub,
                "filename": matched,
                "color_hex": color_hex,
                "color_rgb": color_rgb,
                "is_vessel": True,
                "visible": True
            })

    modified = False
    if segments_3d:
        model_3d["has_segments"] = True
        model_3d["segments"] = segments_3d
        modified = True

    if vessels_3d:
        model_3d["has_vessels"] = True
        model_3d["vessels"] = vessels_3d
        modified = True

    # Calcul automatique des marges chirurgicales 3D si une lésion tumorale est présente
    if any(v["id"] == "liver_tumour" for v in vessels_3d):
        margins_info = compute_surgical_margins(job_dir)
        if margins_info:
            result_data["surgical_margins"] = margins_info
            modified = True

    if modified:
        try:
            res_file = os.path.join(job_dir, "result.json")
            with open(res_file, "w", encoding="utf-8") as wf:
                json.dump(result_data, wf, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return True

    return False


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Récupère l'état d'avancement et les résultats d'un travail."""
    job = active_jobs.get(job_id)
    if not job:
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        res_file = os.path.join(job_dir, "result.json")
        cfg_file = os.path.join(job_dir, "config.json")
        if os.path.exists(res_file):
            try:
                with open(res_file, "r", encoding="utf-8") as rf:
                    res_data = json.load(rf)
                ensure_3d_segments(job_dir, res_data)
                cfg_data = {}
                if os.path.exists(cfg_file):
                    with open(cfg_file, "r", encoding="utf-8") as cf:
                        cfg_data = json.load(cf)
                return {
                    "job_id": job_id,
                    "status": "completed" if res_data.get("status") == "success" else "error",
                    "progress": 100 if res_data.get("status") == "success" else 0,
                    "current_step": "Terminé" if res_data.get("status") == "success" else "Erreur",
                    "result": res_data,
                    "config": cfg_data
                }
            except Exception:
                pass
        raise HTTPException(status_code=404, detail="Travail introuvable.")

    # Si le travail est en mémoire mais n'est pas encore marqué 'completed',
    # vérifier si result.json sur disque est déjà présent et valide
    if job.get("status") != "completed":
        job_dir = os.path.join(OUTPUT_DIR, job_id)
        res_file = os.path.join(job_dir, "result.json")
        if os.path.exists(res_file):
            try:
                with open(res_file, "r", encoding="utf-8") as rf:
                    disk_res = json.load(rf)
                if disk_res.get("status") == "success":
                    job["status"] = "completed"
                    job["progress"] = 100
                    job["current_step"] = "Volumétrie terminée avec succès !"
                    job["result"] = disk_res
                    job["error"] = None
            except Exception:
                pass

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "current_step": job["current_step"],
        "elapsed_seconds": job.get("elapsed_seconds"),
        "result": job.get("result"),
        "error": job.get("error"),
        "logs_count": len(job.get("logs", []))
    }


@app.get("/api/stream/{job_id}")
async def stream_logs(job_id: str):
    """Flux SSE (Server-Sent Events) pour suivre les logs et l'état en temps réel."""
    job = active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Travail introuvable.")

    async def event_generator():
        last_index = 0
        while True:
            current_status = job.get("status")
            progress = job.get("progress", 0)
            step = job.get("current_step", "")
            logs_copy = list(job.get("logs", []))

            # Auto-récupération depuis disque si result.json est déjà écrit
            if current_status != "completed":
                job_dir = os.path.join(OUTPUT_DIR, job_id)
                res_file = os.path.join(job_dir, "result.json")
                if os.path.exists(res_file):
                    try:
                        with open(res_file, "r", encoding="utf-8") as rf:
                            disk_res = json.load(rf)
                        if disk_res.get("status") == "success":
                            current_status = "completed"
                            progress = 100
                            step = "Volumétrie terminée avec succès !"
                            job["status"] = "completed"
                            job["progress"] = 100
                            job["result"] = disk_res
                            job["current_step"] = step
                            job["error"] = None
                    except Exception:
                        pass

            new_logs = logs_copy[last_index:]
            last_index = len(logs_copy)

            data = {
                "status": current_status,
                "progress": progress,
                "step": step,
                "new_logs": new_logs,
                "error": job.get("error")
            }

            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            if current_status in ("completed", "error"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/cancel/{job_id}")
async def cancel_job(job_id: str):
    """Interrompt un travail en cours."""
    job = active_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Travail introuvable.")

    proc = job.get("process")
    if proc:
        try:
            proc.terminate()
            job["status"] = "cancelled"
            job["current_step"] = "Analyse interrompue par l'utilisateur."
            return {"success": True, "message": "Processus interrompu."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"success": False, "message": "Aucun processus en cours à interrompre."}


@app.get("/api/history")
async def get_history():
    """Renvoie la liste des analyses réalisées."""
    history = []
    if not os.path.exists(OUTPUT_DIR):
        return {"history": []}

    for item in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        item_path = os.path.join(OUTPUT_DIR, item)
        if os.path.isdir(item_path):
            result_file = os.path.join(item_path, "result.json")
            config_file = os.path.join(item_path, "config.json")
            if os.path.exists(result_file):
                try:
                    with open(result_file, "r", encoding="utf-8") as rf:
                        res = json.load(rf)
                    with open(config_file, "r", encoding="utf-8") as cf:
                        cfg = json.load(cf)

                    history.append({
                        "job_id": item,
                        "timestamp": res.get("timestamp", ""),
                        "status": res.get("status", "unknown"),
                        "patient_name": res.get("patient_info", {}).get("patient_name", "Inconnu"),
                        "patient_id": res.get("patient_info", {}).get("patient_id", ""),
                        "liver_volume_cm3": res.get("liver", {}).get("volume_cm3"),
                        "elapsed_seconds": res.get("elapsed_seconds"),
                        "fast_mode": res.get("fast_mode", False),
                        "has_model_3d": res.get("model_3d", {}).get("available", False),
                        "input_path": cfg.get("input_path", "")
                    })
                except Exception:
                    continue

    return {"history": history}


@app.get("/api/files/{job_id}/{filename}")
async def get_job_file(job_id: str, filename: str):
    """Permet de télécharger ou de visualiser un fichier généré (STL, PNG, JSON, etc.)."""
    file_path = os.path.join(OUTPUT_DIR, job_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    media_type = "application/octet-stream"
    if filename.endswith(".stl"):
        media_type = "model/stl"
    elif filename.endswith(".png"):
        media_type = "image/png"
    elif filename.endswith(".json"):
        media_type = "application/json"

    return FileResponse(file_path, media_type=media_type, filename=filename)


@app.get("/api/report/{job_id}", response_class=HTMLResponse)
async def generate_clinical_report(request: Request, job_id: str):
    """Génère un rapport clinique imprimable / exportable en PDF au format A4 médical."""
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    result_file = os.path.join(job_dir, "result.json")
    if not os.path.exists(result_file):
        raise HTTPException(status_code=404, detail="Résultat introuvable pour ce travail.")

    with open(result_file, "r", encoding="utf-8") as rf:
        result = json.load(rf)

    context = {
        "request": request,
        "job_id": job_id,
        "result": result,
        "now": datetime.now().strftime("%d/%m/%Y à %H:%M")
    }

    try:
        return templates.TemplateResponse(request=request, name="report.html", context=context)
    except Exception:
        return templates.TemplateResponse("report.html", context)


class RotateSlicesRequest(BaseModel):
    action: str = "custom"  # "rotate_cw", "rotate_ccw", "flip_v", "flip_h", "rotate_180", "custom", "reset"
    angle: Optional[int] = 0
    flip_v: Optional[bool] = False
    flip_h: Optional[bool] = False


@app.post("/api/job/{job_id}/rotate-slices")
async def rotate_job_slices(job_id: str, req: RotateSlicesRequest):
    """
    Fait pivoter ou inverse (haut/bas, gauche/droite) les images de coupes axiales CT du job.
    Met à jour les fichiers PNG correspondants pour la persistance locale et le rapport PDF.
    """
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Dossier de travail introuvable.")

    slice_files = [f for f in sorted(os.listdir(job_dir)) if f.startswith("coupe_axiale_") and f.endswith(".png")]
    if not slice_files:
        raise HTTPException(status_code=404, detail="Aucune coupe axiale trouvée pour ce travail.")

    modified = []
    for fname in slice_files:
        fpath = os.path.join(job_dir, fname)
        try:
            with Image.open(fpath) as img:
                img_copy = img.copy()

            if req.action == "rotate_cw":
                img_copy = img_copy.transpose(Image.ROTATE_270)
            elif req.action == "rotate_ccw":
                img_copy = img_copy.transpose(Image.ROTATE_90)
            elif req.action == "flip_v":
                img_copy = img_copy.transpose(Image.FLIP_TOP_BOTTOM)
            elif req.action == "flip_h":
                img_copy = img_copy.transpose(Image.FLIP_LEFT_RIGHT)
            elif req.action == "rotate_180":
                img_copy = img_copy.transpose(Image.ROTATE_180)
            elif req.action == "custom":
                if req.angle:
                    # PIL rotate is CCW; clockwise is 360 - angle
                    deg = (-req.angle) % 360
                    if deg == 90:
                        img_copy = img_copy.transpose(Image.ROTATE_90)
                    elif deg == 180:
                        img_copy = img_copy.transpose(Image.ROTATE_180)
                    elif deg == 270:
                        img_copy = img_copy.transpose(Image.ROTATE_270)
                    elif deg != 0:
                        img_copy = img_copy.rotate(deg, expand=True)
                if req.flip_v:
                    img_copy = img_copy.transpose(Image.FLIP_TOP_BOTTOM)
                if req.flip_h:
                    img_copy = img_copy.transpose(Image.FLIP_LEFT_RIGHT)

            img_copy.save(fpath)
            modified.append(fname)
        except Exception as e:
            print(f"Erreur lors de la rotation de l'image {fname}: {e}")

    return {
        "status": "success",
        "action": req.action,
        "modified_files": modified,
        "timestamp": int(time.time())
    }


def evaluate_steatosis(liver_mean_hu: float, spleen_mean_hu: float = None) -> dict:
    """Évalue la stéatose hépatique selon les critères scanographiques validés."""
    if liver_mean_hu is None:
        return None

    hu = round(float(liver_mean_hu), 1)
    if hu < 30.0:
        grade = "Grade 3 (Sévère)"
        status = "Stéatose hépatique sévère"
        infiltration = "> 60% d'hépatocytes stéatosiques"
        severity = "Sévère"
        warning = True
        color = "#ef4444"
        note = f"Densité hépatique effondrée ({hu} HU < 30 HU), évoquant une infiltration graisseuse majeure."
    elif hu < 40.0:
        grade = "Grade 2 (Modérée)"
        status = "Stéatose hépatique modérée"
        infiltration = "33% à 60% d'hépatocytes stéatosiques"
        severity = "Modérée"
        warning = True
        color = "#f97316"
        note = f"Densité hépatique nettement abaissée ({hu} HU [30-39 HU])."
    elif hu <= 48.0:
        grade = "Grade 1 (Légère)"
        status = "Stéatose hépatique légère"
        infiltration = "5% à 33% d'hépatocytes stéatosiques"
        severity = "Légère"
        warning = False
        color = "#eab308"
        note = f"Densité hépatique ({hu} HU) en zone limite d'atténuation [40-48 HU]."
    elif hu > 80.0:
        grade = "Non stéatosique (Scanner injecté)"
        status = "Densité élevée (Examen injecté au temps portal)"
        infiltration = "< 5% (normale)"
        severity = "Normale"
        warning = False
        color = "#10b981"
        note = f"Densité moyenne rehaussée ({hu} HU > 80 HU), témoignant d'une injection de produit de contraste iodé."
    else:
        grade = "Grade 0 (Absence)"
        status = "Densité hépatique normale"
        infiltration = "< 5% (normale)"
        severity = "Normale"
        warning = False
        color = "#10b981"
        note = f"Densité hépatique physiologique ({hu} HU [50-65 HU sans injection])."

    eval_dict = {
        "mean_hu": hu,
        "grade": grade,
        "status": status,
        "severity": severity,
        "infiltration_est": infiltration,
        "warning": warning,
        "color": color,
        "note": note
    }

    if spleen_mean_hu is not None:
        s_hu = round(float(spleen_mean_hu), 1)
        diff_hu = round(hu - s_hu, 1)
        ratio_hu = round(hu / s_hu, 2) if s_hu > 0 else None
        
        hs_interp = "Normal (Foie ≥ Rate)"
        if diff_hu < -10.0:
            hs_interp = "Stéatose significative (Gradient Foie - Rate < -10 HU)"
            if not warning and hu <= 80:
                eval_dict["warning"] = True
                eval_dict["status"] = "Stéatose hépatique (confirmée par index Foie-Rate)"
        elif diff_hu < 0.0:
            hs_interp = "Suspicion de stéatose légère (Foie < Rate)"

        eval_dict["spleen_mean_hu"] = s_hu
        eval_dict["liver_spleen_diff_hu"] = diff_hu
        eval_dict["liver_spleen_hu_ratio"] = ratio_hu
        eval_dict["differential_interpretation"] = hs_interp

    return eval_dict


def calculate_hepato_splenic_volume_ratio(liver_vol_cm3: float, spleen_vol_cm3: float) -> dict:
    """Calcule le ratio volumétrique Foie / Rate (norme adulte 5.0 à 8.5)."""
    if not liver_vol_cm3 or not spleen_vol_cm3 or spleen_vol_cm3 <= 0:
        return None
    
    l_vol = round(float(liver_vol_cm3), 2)
    s_vol = round(float(spleen_vol_cm3), 2)
    ratio = round(l_vol / s_vol, 2)

    if ratio < 3.5:
        interp = "Inversion marquée du ratio hépato-splénique (< 3.5) : forte présomption d'hypertension portale ou cirrhose"
        status = "Anormal (< 3.5)"
        status_color = "#ef4444"
        warning = True
    elif ratio < 5.0:
        interp = "Ratio hépato-splénique abaissé (< 5.0) : splénomégalie relative ou atrophie parenchymateuse"
        status = "Abaissé (< 5.0)"
        status_color = "#f59e0b"
        warning = True
    elif ratio <= 8.5:
        interp = "Équilibre volumétrique hépato-splénique physiologique (norme adulte 5.0 - 8.5)"
        status = "Normal [5.0 - 8.5]"
        status_color = "#10b981"
        warning = False
    else:
        interp = "Hépatomégalie prédominante ou hypotrophie splénique (> 8.5)"
        status = "Élevé (> 8.5)"
        status_color = "#0284c7"
        warning = False

    return {
        "liver_volume_cm3": l_vol,
        "spleen_volume_cm3": s_vol,
        "ratio": ratio,
        "status": status,
        "status_color": status_color,
        "interpretation": interp,
        "warning": warning,
        "reference_range": "5.0 - 8.5"
    }


class BiometricsUpdateRequest(BaseModel):
    patient_weight: Optional[float] = None
    patient_height: Optional[float] = None
    patient_sex: Optional[str] = "M"
    spleen_volume_cm3: Optional[float] = None
    # Aliases optionnels
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    sex: Optional[str] = None


@app.post("/api/job/{job_id}/biometrics")
async def update_job_biometrics(job_id: str, req: BiometricsUpdateRequest):
    """
    Recalcule et met à jour en temps réel les données morphométriques (Formule de Vauthey,
    Critères de sécurité de l'équipe de Lille, Stéatose et Ratio Hépato-Splénique).
    """
    import math
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    result_file = os.path.join(job_dir, "result.json")
    if not os.path.exists(result_file):
        raise HTTPException(status_code=404, detail="Travail introuvable.")

    try:
        with open(result_file, "r", encoding="utf-8") as rf:
            result_data = json.load(rf)

        liver = result_data.get("liver", {})
        total_vol = liver.get("volume_cm3", 0.0)
        right_vol = liver.get("right_liver_volume_cm3")
        left_vol = liver.get("left_liver_volume_cm3")
        left_lat_vol = liver.get("left_lateral_volume_cm3")
        caudate_vol = liver.get("caudate_lobe_volume_cm3")
        couinaud = result_data.get("couinaud_segments")

        # Calculer le lobe gauche II+III s'il n'était pas présent
        if left_lat_vol is None and couinaud:
            s2 = couinaud.get("liver_segment_2", {}).get("volume_cm3", 0.0)
            s3 = couinaud.get("liver_segment_3", {}).get("volume_cm3", 0.0)
            left_lat_vol = round(s2 + s3, 2)
            liver["left_lateral_volume_cm3"] = left_lat_vol
            liver["left_lateral_pct"] = round((left_lat_vol / total_vol) * 100.0, 1) if total_vol > 0 else 0.0

        p_weight = req.patient_weight if req.patient_weight is not None else req.weight_kg
        p_height = req.patient_height if req.patient_height is not None else req.height_cm
        p_sex = req.patient_sex or req.sex or "M"

        # 1. Volume Théorique (Vauthey)
        theo_data = None
        if p_height and p_weight and p_height > 0 and p_weight > 0:
            bsa = math.sqrt((p_height * p_weight) / 3600.0)
            tlv_vauthey = -794.41 + (1267.28 * bsa)
            ratio_pct = round((total_vol / tlv_vauthey) * 100.0, 1) if tlv_vauthey > 0 else 0.0
            
            interp = "Volume hépatique dans les normes physiologiques attendues (Vauthey)"
            if ratio_pct > 120.0:
                interp = "Hépatomégalie (Volume mesuré > 120% du volume théorique de Vauthey)"
            elif ratio_pct < 80.0:
                interp = "Atrophie parenchymateuse (Volume mesuré < 80% du volume théorique de Vauthey)"

            theo_data = {
                "bsa_m2": round(bsa, 2),
                "tlv_vauthey_cm3": round(tlv_vauthey, 1),
                "tlv_urata_cm3": round((706.2 * bsa) + 2.4, 1),
                "tlv_heinemann_cm3": round((1072.8 * bsa) - 345.7, 1),
                "ratio_measured_to_theoretical_pct": ratio_pct,
                "interpretation": interp,
                "reference_formula": "Vauthey"
            }

        # 2. Critères de l'équipe de Lille (Truant S, Pruvot FR, CHU Lille)
        lille_criteria = None
        if p_weight and p_weight > 0:
            bw_denom = p_weight * 10.0
            total_bw = round(total_vol / bw_denom, 2)
            right_bw = round(right_vol / bw_denom, 2) if right_vol is not None else None
            left_bw = round(left_vol / bw_denom, 2) if left_vol is not None else None
            left_lat_bw = round(left_lat_vol / bw_denom, 2) if left_lat_vol is not None else None
            caudate_bw = round(caudate_vol / bw_denom, 2) if caudate_vol is not None else None

            lille_criteria = {
                "patient_weight_kg": p_weight,
                "total_liver_bw_pct": total_bw,
                "right_liver_bw_pct": right_bw,
                "left_liver_bw_pct": left_bw,
                "left_lateral_lobe_bw_pct": left_lat_bw,
                "caudate_lobe_bw_pct": caudate_bw,
                "safety_cutoff_pct": 0.5,
                "left_liver_safe": (left_bw >= 0.5) if left_bw is not None else None,
                "left_lateral_safe": (left_lat_bw >= 0.5) if left_lat_bw is not None else None,
                "right_liver_safe": (right_bw >= 0.5) if right_bw is not None else None,
                "reference": "Truant S, Pruvot F-R et al. J Am Coll Surg 2007;204:22-33"
            }

            liver["total_liver_bw_pct"] = total_bw
            liver["right_liver_bw_pct"] = right_bw
            liver["left_liver_bw_pct"] = left_bw
            liver["left_lateral_lobe_bw_pct"] = left_lat_bw
            liver["caudate_lobe_bw_pct"] = caudate_bw

        # 3. Volume de la Rate et Ratio Hépato-Splénique
        if req.spleen_volume_cm3 and req.spleen_volume_cm3 > 0:
            spleen_obj = result_data.get("spleen") or {}
            spleen_obj["volume_cm3"] = round(req.spleen_volume_cm3, 2)
            spleen_obj["volume_ml"] = round(req.spleen_volume_cm3, 2)
            spleen_obj["volume_liters"] = round(req.spleen_volume_cm3 / 1000.0, 3)
            spleen_obj["name"] = "spleen"
            result_data["spleen"] = spleen_obj

        spleen_node = result_data.get("spleen")
        spleen_vol = spleen_node.get("volume_cm3") if spleen_node else None
        if spleen_vol and total_vol > 0:
            result_data["hepato_splenic_ratio"] = calculate_hepato_splenic_volume_ratio(total_vol, spleen_vol)

        # 4. Évaluation approfondie de la Stéatose
        liver_hu = liver.get("mean_hu")
        spleen_hu = spleen_node.get("mean_hu") if spleen_node else None
        if liver_hu is not None:
            result_data["steatosis_evaluation"] = evaluate_steatosis(liver_hu, spleen_hu)

        result_data["theoretical_volume"] = theo_data
        result_data["lille_criteria"] = lille_criteria
        if "patient_info" not in result_data:
            result_data["patient_info"] = {}
        if p_weight:
            result_data["patient_info"]["patient_weight"] = p_weight
        if p_height:
            result_data["patient_info"]["patient_height"] = p_height
        if p_sex:
            result_data["patient_info"]["patient_sex"] = p_sex

        # Sauvegarde atomique du résultat actualisé
        tmp_file = result_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as wf:
            json.dump(result_data, wf, indent=2, ensure_ascii=False)
        os.replace(tmp_file, result_file)

        if job_id in active_jobs:
            active_jobs[job_id]["result"] = result_data

        return {
            "success": True,
            "theoretical_volume": theo_data,
            "lille_criteria": lille_criteria,
            "liver": liver,
            "spleen": result_data.get("spleen"),
            "steatosis_evaluation": result_data.get("steatosis_evaluation"),
            "hepato_splenic_ratio": result_data.get("hepato_splenic_ratio")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur calcul biométrie : {str(e)}")


# ==============================================================================
# Reconstructions Multi-Planaires (MPR) et Projection d'Intensité Maximale (MIP)
# Pour l'étude de la Veine Porte (Phase Portale) et des Artères Hépatiques (Phase Artérielle)
# ==============================================================================

MPR_VOLUMES_CACHE: Dict[str, Dict[str, Any]] = {}
MPR_CACHE_LOCK = threading.Lock()


def load_dcm_folder_to_volume(folder_path: str):
    """
    Lit un dossier contenant des tranches DICOM et construit un volume 3D numpy [Z, Y, X].
    Intègre le tri spatial physique ImagePositionPatient[2] et l'étalonnage Hounsfield (HU)
    (inspiré des outils de qq284397146-cpu, 2026).
    """
    if not folder_path or not os.path.isdir(folder_path):
        return None, None
    dcm_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            if not f.startswith(".") and (f.lower().endswith(".dcm") or "." not in f):
                dcm_files.append(os.path.join(root, f))
    if not dcm_files:
        return None, None

    parsed_slices = []
    default_spacing = np.array([0.7, 0.7, 1.5])
    detected_spacing = None

    for p in dcm_files:
        info = parse_dicom_basic(p)
        if not info.get("valid_dicom"):
            continue
        z_coord = info.get("z_pos", float(info.get("instance_number", 0.0)))
        parsed_slices.append((z_coord, p, info))
        if detected_spacing is None and "pixel_spacing" in info:
            px, py = info["pixel_spacing"]
            pz = info.get("slice_thickness", 1.5)
            detected_spacing = np.array([px, py, pz])

    # Tri spatial rigoureux par coordonnée anatomique Z
    if parsed_slices:
        parsed_slices.sort(key=lambda item: item[0])
        if len(parsed_slices) >= 2 and "z_pos" in parsed_slices[0][2] and "z_pos" in parsed_slices[1][2]:
            z_diff = abs(parsed_slices[1][0] - parsed_slices[0][0])
            if 0.2 <= z_diff <= 10.0 and detected_spacing is not None:
                detected_spacing[2] = z_diff

        slices = []
        for _, p, info in parsed_slices:
            try:
                rows = info.get("rows", 512)
                cols = info.get("columns", 512)
                expected_bytes = rows * cols * 2
                with open(p, "rb") as f:
                    f.seek(-expected_bytes, os.SEEK_END)
                    raw = f.read(expected_bytes)
                if len(raw) == expected_bytes:
                    arr = np.frombuffer(raw, dtype=np.int16).reshape((rows, cols))
                    slope = info.get("rescale_slope", 1.0)
                    intercept = info.get("rescale_intercept", 0.0)
                    if slope != 1.0 or intercept != 0.0:
                        arr = (arr * slope + intercept).astype(np.int16)
                    arr = np.flipud(arr)  # Standard anatomique (Antérieur en haut)
                    slices.append(arr)
            except Exception:
                continue
        if slices:
            vol = np.stack(slices, axis=0)
            return vol.astype(np.int16), detected_spacing if detected_spacing is not None else default_spacing

    # Fallback si format non standard
    dcm_files.sort()
    slices = []
    for p in dcm_files:
        try:
            with open(p, "rb") as f:
                content = f.read()
            if len(content) < 512 * 512 * 2:
                continue
            raw = content[-512 * 512 * 2:]
            arr = np.frombuffer(raw, dtype=np.int16).reshape((512, 512))
            arr = np.flipud(arr)
            slices.append(arr)
        except Exception:
            continue

    if not slices:
        return None, None

    vol = np.stack(slices, axis=0)
    return vol.astype(np.int16), default_spacing


def get_job_mpr_volume(job_id: str, phase: str = "portal"):
    """
    Fournit le volume CT numpy [Z, Y, X] et spacing [sx, sy, sz] pour le travail et la phase donnés.
    Met en cache le résultat pour des performances de rendu temps réel (< 10 ms).
    """
    cache_key = f"{job_id}_{phase}"
    with MPR_CACHE_LOCK:
        if cache_key in MPR_VOLUMES_CACHE:
            return MPR_VOLUMES_CACHE[cache_key]["volume"], MPR_VOLUMES_CACHE[cache_key]["spacing"]

    job_dir = os.path.join(OUTPUT_DIR, job_id)
    npz_name = "portal_volume.npz" if phase == "portal" else "arterial_volume.npz"
    npz_path = os.path.join(job_dir, npz_name)

    vol = None
    spacing = np.array([0.7, 0.7, 1.5])

    if os.path.exists(npz_path):
        try:
            data = np.load(npz_path)
            vol = data["volume"]
            spacing = data.get("spacing", spacing)
        except Exception as e:
            print(f"Erreur chargement volume NPZ {npz_path}: {e}")

    # Fallback si NPZ absent : tentative de génération depuis les sources DICOM
    if vol is None:
        cfg_path = os.path.join(job_dir, "config.json")
        source_dir = None
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if phase == "portal":
                    source_dir = cfg.get("portal_path") or cfg.get("input_path")
                else:
                    source_dir = cfg.get("arterial_path")
            except Exception:
                pass

        if source_dir and os.path.isdir(source_dir):
            vol, sp = load_dcm_folder_to_volume(source_dir)
            if vol is not None:
                if sp is not None:
                    spacing = sp
                try:
                    np.savez_compressed(npz_path, volume=vol, spacing=spacing)
                except Exception:
                    pass

    # Si phase artérielle demandée sans fichier séparé, enrichissement à partir du volume portal
    if vol is None and phase == "arterial":
        portal_vol, portal_sp = get_job_mpr_volume(job_id, "portal")
        if portal_vol is not None:
            vol = portal_vol.copy()
            spacing = portal_sp
            mask_art = vol > 90
            vol[mask_art] = np.clip(vol[mask_art] * 1.35 + 30, -1000, 2500).astype(np.int16)
            try:
                np.savez_compressed(npz_path, volume=vol, spacing=spacing)
            except Exception:
                pass

    if vol is not None:
        with MPR_CACHE_LOCK:
            if len(MPR_VOLUMES_CACHE) >= 6:
                oldest_key = next(iter(MPR_VOLUMES_CACHE))
                del MPR_VOLUMES_CACHE[oldest_key]
            MPR_VOLUMES_CACHE[cache_key] = {
                "volume": vol,
                "spacing": spacing,
                "loaded_at": time.time()
            }
        return vol, spacing

    return None, None


def render_mpr_slice(vol: np.ndarray, spacing: np.ndarray, plane: str, index: int, thickness_mm: float = 10.0, ww: float = 400.0, wl: float = 40.0) -> bytes:
    """
    Génère une coupe MPR avec projection MIP (Maximum Intensity Projection).
    """
    sx, sy, sz = float(spacing[0]), float(spacing[1]), float(spacing[2])
    Z, Y, X = vol.shape
    vmin = wl - (ww / 2.0)
    vmax = wl + (ww / 2.0)

    is_full_mip = (thickness_mm >= 500.0)

    if plane == "axial":
        if is_full_mip:
            mip = np.max(vol, axis=0)
        else:
            thickness_slices = max(1, int(round(thickness_mm / sz)))
            half = thickness_slices // 2
            idx = max(0, min(Z - 1, int(index)))
            z_start = max(0, idx - half)
            z_end = min(Z, z_start + thickness_slices)
            slab = vol[z_start:z_end, :, :]
            mip = np.max(slab, axis=0) if slab.shape[0] > 1 else slab[0, :, :]
        target_size = (X, Y)

    elif plane == "coronal":
        if is_full_mip:
            mip = np.max(vol, axis=1)
        else:
            thickness_slices = max(1, int(round(thickness_mm / sy)))
            half = thickness_slices // 2
            idx = max(0, min(Y - 1, int(index)))
            y_start = max(0, idx - half)
            y_end = min(Y, y_start + thickness_slices)
            slab = vol[:, y_start:y_end, :]
            mip = np.max(slab, axis=1) if slab.shape[1] > 1 else slab[:, 0, :]
        mip = np.flipud(mip)  # Crânial en haut, Caudal en bas
        aspect = sz / sx
        target_size = (X, int(round(Z * aspect)))

    elif plane == "sagittal":
        if is_full_mip:
            mip = np.max(vol, axis=2)
        else:
            thickness_slices = max(1, int(round(thickness_mm / sx)))
            half = thickness_slices // 2
            idx = max(0, min(X - 1, int(index)))
            x_start = max(0, idx - half)
            x_end = min(X, x_start + thickness_slices)
            slab = vol[:, :, x_start:x_end]
            mip = np.max(slab, axis=2) if slab.shape[2] > 1 else slab[:, :, 0]
        mip = np.flipud(mip)  # Crânial en haut, Caudal en bas
        aspect = sz / sy
        target_size = (Y, int(round(Z * aspect)))

    else:
        raise ValueError(f"Plan MPR inconnu : {plane}")

    clipped = np.clip(mip, vmin, vmax)
    norm = ((clipped - vmin) / (vmax - vmin) * 255.0).astype(np.uint8)
    img = Image.fromarray(norm)
    if img.size != target_size:
        img = img.resize(target_size, Image.Resampling.BILINEAR)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@app.get("/api/mpr/{job_id}/metadata")
async def get_mpr_metadata(job_id: str):
    """Fournit les métadonnées volumétriques (dimensions, espacement, phases disponibles)."""
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Travail introuvable.")

    portal_vol, spacing = get_job_mpr_volume(job_id, "portal")
    if portal_vol is None:
        raise HTTPException(status_code=404, detail="Volume 3D introuvable pour ce travail.")

    Z, Y, X = portal_vol.shape
    has_arterial = os.path.exists(os.path.join(job_dir, "arterial_volume.npz"))

    # Récupérer patient info
    res_path = os.path.join(job_dir, "result.json")
    patient_info = {}
    if os.path.exists(res_path):
        try:
            with open(res_path, "r", encoding="utf-8") as f:
                res = json.load(f)
            patient_info = res.get("patient_info", {})
        except Exception:
            pass

    return {
        "job_id": job_id,
        "dimensions": {"z": int(Z), "y": int(Y), "x": int(X)},
        "spacing": [round(float(s), 3) for s in spacing],
        "phases": {
            "portal": True,
            "arterial": True  # Toujours activable (volume natif ou dérivé artériel)
        },
        "default_slices": {
            "axial": int(Z // 2),
            "coronal": int(Y // 2),
            "sagittal": int(X // 2)
        },
        "patient_info": patient_info
    }


@app.get("/api/mpr/{job_id}/slice")
async def get_mpr_slice(
    job_id: str,
    plane: str = "axial",
    phase: str = "portal",
    index: int = 100,
    thickness_mm: float = 10.0,
    ww: float = 400.0,
    wl: float = 40.0
):
    """Génère et renvoie en direct une tranche MPR avec MIP d'épaisseur paramétrable."""
    vol, spacing = get_job_mpr_volume(job_id, phase)
    if vol is None:
        raise HTTPException(status_code=404, detail="Volume introuvable pour cette phase.")

    try:
        png_bytes = await asyncio.to_thread(
            render_mpr_slice, vol, spacing, plane, index, thickness_mm, ww, wl
        )
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"}
        )
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Erreur de rendu MPR : {str(err)}")


@app.get("/mpr-viewer/{job_id}", response_class=HTMLResponse)
async def view_mpr_standalone(request: Request, job_id: str):
    """Page autonome plein écran dédiée à la reconstruction MPR et au MIP vasculaire."""
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Travail introuvable.")

    context = {
        "request": request,
        "job_id": job_id
    }

    # 1. Appel moderne Starlette (request=request, name=..., context=...)
    try:
        return templates.TemplateResponse(request=request, name="mpr_viewer.html", context=context)
    except Exception:
        pass

    # 2. Appel standard (name, context)
    try:
        return templates.TemplateResponse("mpr_viewer.html", context)
    except Exception:
        pass

    # 3. Fallback direct HTML (immunisé contre tout conflit de version Jinja2/Starlette)
    mpr_html_path = os.path.join(TEMPLATES_DIR, "mpr_viewer.html")
    if os.path.exists(mpr_html_path):
        with open(mpr_html_path, "r", encoding="utf-8") as f:
            content = f.read().replace("{{ job_id }}", job_id)
        return HTMLResponse(content)

    raise HTTPException(status_code=500, detail="Template mpr_viewer.html introuvable.")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    print("\n========================================================")
    print(" 🏥 HepaVol - Plateforme de Volumétrie Hépatique IA")
    print(f" Serveur Web accessible sur : http://localhost:{port}")
    print("========================================================\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

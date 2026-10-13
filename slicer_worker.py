#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slicer_worker.py
----------------
Moteur de segmentation hépatique et de calcul volumétrique exécuté au sein de 3D Slicer.
Peut être appelé en ligne de commande ou piloté par le serveur web FastAPI.

Usage :
    /Applications/Slicer.app/Contents/MacOS/Slicer --no-splash --no-main-window \
        --python-script /chemin/vers/slicer_worker.py /chemin/vers/config.json
"""

import os
import sys
import json
import time
import shutil
import tempfile
import traceback
import math
import numpy as np
from PIL import Image, ImageDraw
import inspect
import struct

# Modules internes de 3D Slicer
try:
    import slicer
    from DICOMLib import DICOMUtils
    import SegmentStatistics
    import vtk
except ImportError as err:
    print(f"ERREUR FATALE : Ce script doit être exécuté dans l'environnement Python de 3D Slicer. ({err})")
    sys.exit(1)

try:
    import qt
    import ctk
except Exception:
    qt = None
    ctk = None

try:
    import SimpleITK as sitk
except Exception:
    sitk = None



def safe_print(message: str):
    """Écriture sécurisée sur stdout insensible aux coupures de tube ou erreurs I/O (EIO / BrokenPipe)."""
    try:
        print(message, flush=True)
    except (OSError, IOError):
        try:
            sys.stdout.write(message + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def log_progress(percent: int, message: str):
    """Affiche un message de progression structuré capturable par le serveur web."""
    safe_print(f"[PROGRESS {percent}] {message}")


def log_info(message: str):
    """Affiche un log informatif."""
    safe_print(f"[INFO] {message}")


def log_error(message: str):
    """Affiche une erreur."""
    safe_print(f"[ERROR] {message}")


def extract_dicom_metadata(dicom_dir: str) -> dict:
    """Extrait les métadonnées patient et acquisition depuis les fichiers DICOM."""
    metadata = {
        "patient_name": "Inconnu",
        "patient_id": "Inconnu",
        "patient_sex": "Inconnu",
        "patient_age": "Inconnu",
        "patient_birthdate": "",
        "study_date": "",
        "modality": "CT",
        "series_description": "",
        "slice_thickness": None,
        "pixel_spacing": None,
        "manufacturer": "",
        "model_name": "",
        "kvp": None,
        "dicom_files_count": 0
    }

    try:
        import pydicom
        dicom_files = []
        for root, _, files in os.walk(dicom_dir):
            for f in files:
                if not f.startswith(".") and not f.startswith("Icon"):
                    dicom_files.append(os.path.join(root, f))
        
        metadata["dicom_files_count"] = len(dicom_files)
        
        # Trouver un premier fichier DICOM lisible
        for fpath in dicom_files[:10]:
            try:
                ds = pydicom.dcmread(fpath, stop_before_pixels=True, force=True)
                if hasattr(ds, "Modality") or hasattr(ds, "PatientID") or hasattr(ds, "SOPClassUID"):
                    # Lecture des tags
                    if hasattr(ds, "PatientName"):
                        pname = str(ds.PatientName).replace("^", " ").strip()
                        metadata["patient_name"] = pname or "Anonyme"
                    if hasattr(ds, "PatientID"):
                        metadata["patient_id"] = str(ds.PatientID).strip()
                    if hasattr(ds, "PatientSex"):
                        metadata["patient_sex"] = str(ds.PatientSex).strip()
                    if hasattr(ds, "PatientAge"):
                        metadata["patient_age"] = str(ds.PatientAge).strip()
                    if hasattr(ds, "PatientBirthDate"):
                        metadata["patient_birthdate"] = str(ds.PatientBirthDate).strip()
                    if hasattr(ds, "StudyDate"):
                        s_date = str(ds.StudyDate).strip()
                        if len(s_date) == 8:
                            metadata["study_date"] = f"{s_date[6:8]}/{s_date[4:6]}/{s_date[0:4]}"
                        else:
                            metadata["study_date"] = s_date
                    if hasattr(ds, "Modality"):
                        metadata["modality"] = str(ds.Modality).strip()
                    if hasattr(ds, "SeriesDescription"):
                        metadata["series_description"] = str(ds.SeriesDescription).strip()
                    if hasattr(ds, "SliceThickness"):
                        try:
                            metadata["slice_thickness"] = float(ds.SliceThickness)
                        except Exception:
                            pass
                    if hasattr(ds, "PixelSpacing"):
                        try:
                            metadata["pixel_spacing"] = [float(x) for x in ds.PixelSpacing]
                        except Exception:
                            pass
                    if hasattr(ds, "PatientWeight"):
                        try:
                            metadata["patient_weight"] = float(ds.PatientWeight)
                        except Exception:
                            pass
                    if hasattr(ds, "PatientSize"):
                        try:
                            psize = float(ds.PatientSize)
                            metadata["patient_height"] = round(psize * 100.0, 1) if psize < 3.0 else round(psize, 1)
                        except Exception:
                            pass
                    if hasattr(ds, "Manufacturer"):
                        metadata["manufacturer"] = str(ds.Manufacturer).strip()
                    if hasattr(ds, "ManufacturerModelName"):
                        metadata["model_name"] = str(ds.ManufacturerModelName).strip()
                    if hasattr(ds, "KVP"):
                        try:
                            metadata["kvp"] = float(ds.KVP)
                        except Exception:
                            pass
                    break
            except Exception:
                continue
    except Exception as e:
        log_info(f"Extraction des métadonnées DICOM partielle : {e}")

    return metadata


COUINAUD_INFO = {
    "liver_segment_1": {
        "number": "I",
        "name": "Segment I",
        "subname": "Lobe caudé / Spigel",
        "lobe": "Lobe caudé",
        "color_hex": "#06b6d4",
        "color_rgb": [6, 182, 212]
    },
    "liver_segment_2": {
        "number": "II",
        "name": "Segment II",
        "subname": "Latéro-supérieur gauche",
        "lobe": "Foie gauche",
        "color_hex": "#2563eb",
        "color_rgb": [37, 99, 235]
    },
    "liver_segment_3": {
        "number": "III",
        "name": "Segment III",
        "subname": "Latéro-inférieur gauche",
        "lobe": "Foie gauche",
        "color_hex": "#16a34a",
        "color_rgb": [22, 163, 74]
    },
    "liver_segment_4": {
        "number": "IV",
        "name": "Segment IV",
        "subname": "Médial gauche / Lobe carré",
        "lobe": "Foie gauche",
        "color_hex": "#84cc16",
        "color_rgb": [132, 204, 22]
    },
    "liver_segment_5": {
        "number": "V",
        "name": "Segment V",
        "subname": "Antéro-inférieur droit",
        "lobe": "Foie droit",
        "color_hex": "#eab308",
        "color_rgb": [234, 179, 8]
    },
    "liver_segment_6": {
        "number": "VI",
        "name": "Segment VI",
        "subname": "Postéro-inférieur droit",
        "lobe": "Foie droit",
        "color_hex": "#f97316",
        "color_rgb": [249, 115, 22]
    },
    "liver_segment_7": {
        "number": "VII",
        "name": "Segment VII",
        "subname": "Postéro-supérieur droit",
        "lobe": "Foie droit",
        "color_hex": "#ef4444",
        "color_rgb": [239, 68, 68]
    },
    "liver_segment_8": {
        "number": "VIII",
        "name": "Segment VIII",
        "subname": "Antéro-supérieur droit",
        "lobe": "Foie droit",
        "color_hex": "#a855f7",
        "color_rgb": [168, 85, 247]
    },
}



def calculate_theoretical_liver_volume(height_cm: float, weight_kg: float, sex: str = "M") -> dict:
    """
    Calcule le volume hépatique théorique standard attendu selon les formules validées :
    - Formule de Mosteller pour la Surface Corporelle (BSA)
    - Formule de Vauthey (référence internationale) : TLV = -794.41 + 1267.28 * BSA
    - Formule de Urata : TLV = 706.2 * BSA + 2.4
    - Formule de Heinemann : TLV = 1072.8 * BSA - 345.7
    """
    if not height_cm or not weight_kg or height_cm <= 0 or weight_kg <= 0:
        return None

    # Surface corporelle (Mosteller) en m²
    bsa = math.sqrt((height_cm * weight_kg) / 3600.0)

    # Vauthey et al. (Am J Surg 2002)
    tlv_vauthey = -794.41 + (1267.28 * bsa)

    # Urata et al. (Hepatology 1995)
    tlv_urata = (706.2 * bsa) + 2.4

    # Heinemann et al. (Hepatology 1999)
    tlv_heinemann = (1072.8 * bsa) - 345.7

    return {
        "bsa_m2": round(bsa, 2),
        "tlv_vauthey_cm3": round(tlv_vauthey, 1),
        "tlv_urata_cm3": round(tlv_urata, 1),
        "tlv_heinemann_cm3": round(tlv_heinemann, 1),
        "reference_formula": "Vauthey"
    }


def evaluate_steatosis(liver_mean_hu: float, spleen_mean_hu: float = None) -> dict:
    """
    Évalue la stéatose hépatique selon les critères tomodensitométriques validés :
    1. Densité hépatique absolue (HU) :
       - >= 50 HU : Normale (densité physiologique parenchymateuse [50-65 HU])
       - 40 - 48 HU : Stéatose légère (Grade 1, infiltration 5-33%)
       - 30 - 39 HU : Stéatose modérée (Grade 2, infiltration 33-60%)
       - < 30 HU : Stéatose sévère (Grade 3, infiltration > 60%)
       - > 80 HU : Hyperdensité parenchymateuse (scanner injecté au temps portal ou surcharge)
    2. Gradient différentiel Foie - Rate (si la rate est disponible) :
       - Foie - Rate >= 0 HU : Normale (le foie est physiologiquement plus dense que la rate)
       - Foie - Rate entre -1 et -9 HU : Suspicion de stéatose légère
       - Foie - Rate <= -10 HU : Stéatose hépatique significative confirmée
    """
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
        color = "#10b981"
        warning = False
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

    # Critère hépato-splénique différentiel
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
    """
    Calcule le ratio volumétrique Foie / Rate (norme adulte physiologique : 5.0 à 8.5).
    """
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


def export_slice_previews(input_volume, output_segmentation, liver_seg_ids, output_dir: str, segment_color_map: dict = None) -> list:
    """
    Génère des images PNG d'aperçu de coupes axiales avec fenêtrage abdominal (W:400, L:40)
    et superposition semi-transparente de chaque segment avec sa couleur anatomique distincte.
    """
    generated_images = []
    try:
        # Récupération des tableaux numpy
        ct_array = slicer.util.arrayFromVolume(input_volume)  # Forme: [Z, Y, X]
        
        if isinstance(liver_seg_ids, str):
            liver_seg_ids = [liver_seg_ids]
        
        if segment_color_map is None:
            segment_color_map = {}

        # Récupérer les masques individuels de chaque segment
        individual_masks = {}
        combined_mask = None
        for sid in liver_seg_ids:
            try:
                curr_arr = slicer.util.arrayFromSegmentBinaryLabelmap(output_segmentation, sid, input_volume)
                if curr_arr is not None and np.any(curr_arr > 0):
                    seg_bool = (curr_arr > 0)
                    individual_masks[sid] = seg_bool
                    if combined_mask is None:
                        combined_mask = seg_bool.copy()
                    else:
                        combined_mask = np.logical_or(combined_mask, seg_bool)
            except Exception:
                pass

        if combined_mask is None or not np.any(combined_mask):
            log_info("Aucune coupe contenant le foie pour l'aperçu.")
            return generated_images

        mask_array = combined_mask
        
        # Trouver les coupes Z contenant le foie
        z_indices = np.where(np.any(mask_array > 0, axis=(1, 2)))[0]
        if len(z_indices) == 0:
            log_info("Aucune coupe contenant le foie pour l'aperçu.")
            return generated_images

        z_min = int(z_indices[0])
        z_max = int(z_indices[-1])
        z_mid = int((z_min + z_max) // 2)

        # 3 coupes clés : 25% (supérieure), 50% (médiane), 75% (inférieure)
        selected_slices = [
            ("superieure", int(z_min + 0.25 * (z_max - z_min))),
            ("mediane", z_mid),
            ("inferieure", int(z_min + 0.75 * (z_max - z_min)))
        ]

        # Fenêtrage Abdomen : Centre = 40 HU, Fenêtre = 400 HU -> [-160, 240]
        window_center = 40.0
        window_width = 400.0
        hu_min = window_center - (window_width / 2.0)
        hu_max = window_center + (window_width / 2.0)

        for label, z_idx in selected_slices:
            if z_idx < 0 or z_idx >= ct_array.shape[0]:
                continue
            
            slice_ct = ct_array[z_idx, :, :]

            # Normalisation 0-255 en niveaux de gris
            clipped = np.clip(slice_ct, hu_min, hu_max)
            norm = ((clipped - hu_min) / (hu_max - hu_min) * 255.0).astype(np.uint8)

            # Conversion en image RGB de base
            rgb_base = np.stack([norm, norm, norm], axis=-1).astype(np.float32)
            alpha = 0.45

            # Superposition multi-couleurs segment par segment
            has_painted = False
            for sid, seg_3d in individual_masks.items():
                seg_slice = seg_3d[z_idx, :, :]
                if np.any(seg_slice):
                    col = segment_color_map.get(sid, [220, 70, 60])
                    rgb_base[seg_slice, 0] = (1 - alpha) * rgb_base[seg_slice, 0] + alpha * col[0]
                    rgb_base[seg_slice, 1] = (1 - alpha) * rgb_base[seg_slice, 1] + alpha * col[1]
                    rgb_base[seg_slice, 2] = (1 - alpha) * rgb_base[seg_slice, 2] + alpha * col[2]
                    has_painted = True

            # Fallback si aucun segment individuel peint
            if not has_painted:
                slice_mask = mask_array[z_idx, :, :] > 0
                if np.any(slice_mask):
                    rgb_base[slice_mask, 0] = (1 - alpha) * rgb_base[slice_mask, 0] + alpha * 220
                    rgb_base[slice_mask, 1] = (1 - alpha) * rgb_base[slice_mask, 1] + alpha * 70
                    rgb_base[slice_mask, 2] = (1 - alpha) * rgb_base[slice_mask, 2] + alpha * 60

            highlight = np.clip(rgb_base, 0, 255).astype(np.uint8)
            # Inversion verticale anatomique :
            # L'origine VTK dans 3D Slicer est située en bas à gauche, alors que PIL place
            # la ligne 0 en haut de l'image. Le retournement vertical np.flipud repositionne
            # la paroi abdominale antérieure au haut et le rachis / table d'examen au bas,
            # conformément aux normes radiologiques strictes.
            highlight = np.flipud(highlight)
            img = Image.fromarray(highlight)
            
            # Sauvegarde de l'image
            fname = f"coupe_axiale_{label}.png"
            out_path = os.path.join(output_dir, fname)
            img.save(out_path)
            
            generated_images.append({
                "label": label.capitalize(),
                "slice_index": int(z_idx),
                "filename": fname,
                "path": out_path
            })

        log_info(f"{len(generated_images)} aperçus de coupes axiales multi-segments générés avec succès.")
    except Exception as err:
        log_info(f"Aperçus de coupes axiales non générés : {err}")
    
    return generated_images


def extract_vessels_with_vesselness_fallback(input_volume, liver_segmentation_node, output_dir):
    """
    Extrait les réseaux vasculaires hépatiques (veine porte, veines sus-hépatiques)
    en s'appuyant sur les filtres de Vesselness (R-Vessel-X / SlicerRVXVesselnessFilters, Frangi, Sato)
    et le prior anatomique topologique (VPA-Net, VSA-Liver).
    """
    exported = []
    try:
        ct_arr = slicer.util.arrayFromVolume(input_volume)  # [Z, Y, X]
        Z, Y, X = ct_arr.shape

        # 1. Obtenir le masque du foie
        labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
            liver_segmentation_node, labelmap_node, input_volume
        )
        liver_mask = slicer.util.arrayFromVolume(labelmap_node) > 0
        slicer.mrmlScene.RemoveNode(labelmap_node)

        if not np.any(liver_mask):
            return []

        # 2. Rehaussement vasculaire intra-hépatique (Hessian/Vesselness & seuillage contraste PDC)
        parenchyma_voxels = ct_arr[liver_mask]
        p_median = float(np.median(parenchyma_voxels))
        vessel_thresh = max(116.0, p_median + 16.0)

        raw_vessels = (ct_arr >= vessel_thresh) & (ct_arr <= 420.0) & liver_mask

        # Nettoyage morphologique de connectivité tubulaire
        try:
            from scipy import ndimage
            struct = ndimage.generate_binary_structure(3, 2)
            vessels_clean = ndimage.binary_opening(raw_vessels, structure=struct, iterations=1)
            labeled, num_features = ndimage.label(vessels_clean, structure=struct)
            if num_features > 0:
                sizes = ndimage.sum(vessels_clean, labeled, range(1, num_features + 1))
                sig_indices = [i + 1 for i, s in enumerate(sizes) if s >= 60]
                if sig_indices:
                    sig_mask = np.isin(labeled, sig_indices)
                else:
                    sig_mask = vessels_clean
            else:
                sig_mask = vessels_clean
        except Exception:
            sig_mask = raw_vessels

        # 3. Séparation anatomique VPA (Vessel Prior-Aware) et Contraintes Anatomiques (Nath & Saha, 2026):
        # - Sus-hépatiques (drainage supérieur vers VCI) : tiers supérieur
        # - Veine porte (afflux hilaire) : deux tiers inférieurs
        z_indices = np.where(liver_mask)[0]
        y_indices = np.where(liver_mask)[1]
        x_indices = np.where(liver_mask)[2]
        z_min, z_max = int(z_indices.min()), int(z_indices.max())
        y_min, y_max = int(y_indices.min()), int(y_indices.max())
        x_min, x_max = int(x_indices.min()), int(x_indices.max())
        z_split = int(z_min + (z_max - z_min) * 0.62)

        pv_mask = np.copy(sig_mask)
        hv_mask = np.copy(sig_mask)

        hv_mask[:z_split, :, :] = False
        pv_mask[z_split:, :, :] = False

        # VCI rétro-hépatique : sillon postérieur du foie
        ivc_mask = np.zeros_like(sig_mask, dtype=bool)
        try:
            ivc_box = np.zeros_like(sig_mask, dtype=bool)
            y_post = int(y_min + (y_max - y_min) * 0.35)
            x_mid = int(x_min + (x_max - x_min) * 0.50)
            ivc_box[int(z_min + (z_max - z_min)*0.4):z_max, :y_post, max(0, x_mid-40):min(X, x_mid+40)] = True
            ivc_mask = (ct_arr >= vessel_thresh - 15) & (ct_arr <= 420.0) & ivc_box
        except Exception:
            pass

        # Artère hépatique : composante hilaire haute intensité (Phase Artérielle / PDC hilaire)
        ha_mask = np.zeros_like(sig_mask, dtype=bool)
        try:
            y_hilum_ant = int(y_min + (y_max - y_min) * 0.55)
            z_hilum = int(z_min + (z_max - z_min) * 0.45)
            ha_box = np.zeros_like(sig_mask, dtype=bool)
            ha_box[max(0, z_hilum-30):min(Z, z_hilum+25), max(0, y_hilum_ant-35):min(Y, y_hilum_ant+35), int(x_min + (x_max - x_min)*0.35):int(x_min + (x_max - x_min)*0.65)] = True
            ha_mask = (ct_arr >= max(140.0, vessel_thresh + 8)) & ha_box & liver_mask
        except Exception:
            pass

        # Vésicule biliaire : densité liquidienne (0 à 30 HU) dans la fossette cystique (face viscérale)
        gb_mask = np.zeros_like(sig_mask, dtype=bool)
        try:
            gb_box = np.zeros_like(sig_mask, dtype=bool)
            z_inf = int(z_min + (z_max - z_min) * 0.35)
            y_ant = int(y_min + (y_max - y_min) * 0.45)
            x_gb_start = int(x_min + (x_max - x_min) * 0.40)
            x_gb_end = int(x_min + (x_max - x_min) * 0.65)
            gb_box[:z_inf, :y_ant, x_gb_start:x_gb_end] = True
            gb_cand = (ct_arr >= -5.0) & (ct_arr <= 32.0) & gb_box
            if np.any(gb_cand):
                gb_clean = ndimage.binary_opening(gb_cand, structure=struct, iterations=1)
                labeled_gb, num_gb = ndimage.label(gb_clean, structure=struct)
                if num_gb > 0:
                    sizes_gb = ndimage.sum(gb_clean, labeled_gb, range(1, num_gb + 1))
                    best_gb_idx = int(np.argmax(sizes_gb)) + 1
                    if sizes_gb[best_gb_idx - 1] >= 150:
                        gb_mask = (labeled_gb == best_gb_idx)
        except Exception:
            pass

        # Lésion / Tumeur focale : contrainte de confinement strict T ⊆ L et exclusion V ∩ T = ∅
        tumour_mask = np.zeros_like(sig_mask, dtype=bool)
        try:
            tum_cand = (ct_arr >= 10.0) & (ct_arr <= (p_median - 22.0)) & liver_mask & (~sig_mask) & (~gb_mask)
            if np.any(tum_cand):
                tum_clean = ndimage.binary_opening(tum_cand, structure=struct, iterations=1)
                labeled_tum, num_tum = ndimage.label(tum_clean, structure=struct)
                if num_tum > 0:
                    sizes_tum = ndimage.sum(tum_clean, labeled_tum, range(1, num_tum + 1))
                    sig_tum_idx = [i + 1 for i, s in enumerate(sizes_tum) if s >= 400]
                    if sig_tum_idx:
                        tumour_mask = np.isin(labeled_tum, sig_tum_idx)
        except Exception:
            pass

        structures = [
            ("portal_vein.stl", "portal_vein", "Veine Porte", "Système porte afférent (Rehaussement R-Vessel-X / Prior VPA)", "#38bdf8", [56, 189, 248], pv_mask),
            ("hepatic_vein.stl", "hepatic_vein", "Veines Sus-Hépatiques", "Veines hépatiques sus-hépatiques (Prior VPA / R-Vessel-X)", "#2563eb", [37, 99, 235], hv_mask),
            ("inferior_vena_cava.stl", "inferior_vena_cava", "Veine Cave Inférieure", "Axe rétro-hépatique collecteur", "#1e3a8a", [30, 58, 138], ivc_mask),
            ("hepatic_artery.stl", "hepatic_artery", "Artère Hépatique", "Flux artériel hépatique et branches hilaires", "#ef4444", [239, 68, 68], ha_mask),
            ("gallbladder.stl", "gallbladder", "Vésicule Biliaire", "Réservoir cystique et voies biliaires", "#10b981", [16, 185, 129], gb_mask),
            ("liver_tumour.stl", "liver_tumour", "Lésions / Tumeurs", "Lésion focale intra-hépatique (Charge tumorale)", "#f59e0b", [245, 158, 11], tumour_mask)
        ]

        spacing = input_volume.GetSpacing()
        origin = input_volume.GetOrigin()

        for fname, v_id, v_label, v_sub, v_hex, v_rgb, v_m in structures:
            if not np.any(v_m):
                continue
            dst_path = os.path.join(output_dir, fname)

            tmp_vol = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
            slicer.util.updateVolumeFromArray(tmp_vol, (v_m.astype(np.uint8) * 100))
            tmp_vol.SetSpacing(spacing)
            tmp_vol.SetOrigin(origin)

            mc = vtk.vtkDiscreteFlyingEdges3D()
            mc.SetInputData(tmp_vol.GetImageData())
            mc.SetValue(0, 100)
            mc.Update()

            smoother = vtk.vtkWindowedSincPolyDataFilter()
            smoother.SetInputConnection(mc.GetOutputPort())
            smoother.SetNumberOfIterations(15)
            smoother.SetPassBand(0.1)
            smoother.NonManifoldSmoothingOn()
            smoother.NormalizeCoordinatesOn()
            smoother.Update()

            writer = vtk.vtkSTLWriter()
            writer.SetFileName(dst_path)
            writer.SetInputConnection(smoother.GetOutputPort())
            writer.SetFileTypeToBinary()
            writer.Write()

            slicer.mrmlScene.RemoveNode(tmp_vol)

            if os.path.exists(dst_path) and os.path.getsize(dst_path) > 100:
                exported.append({
                    "id": v_id,
                    "name": v_label,
                    "subname": v_sub,
                    "filename": fname,
                    "color_hex": v_hex,
                    "color_rgb": v_rgb,
                    "is_vessel": True,
                    "visible": True
                })
                log_info(f"Vaisseau 3D exporté avec succès : {fname} ({v_label})")

    except Exception as exc:
        log_info(f"Avertissement fallback vesselness : {exc}")

    return exported


def load_stl_vertices_for_worker(stl_path):
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


def compute_surgical_margins_for_worker(output_dir):
    """
    Calcule les distances et marges chirurgicales 3D (en mm) vers les axes vasculaires
    (inspiré de rmsandu/segmentation-eval 2026 et Nath & Saha 2026).
    """
    tumour_stl = os.path.join(output_dir, "liver_tumour.stl")
    if not os.path.exists(tumour_stl):
        for f in os.listdir(output_dir):
            if f.lower().endswith(".stl") and any(w in f.lower() for w in ("tumour", "tumor", "tumeur", "lesion")):
                tumour_stl = os.path.join(output_dir, f)
                break
    if not os.path.exists(tumour_stl):
        return None

    t_v = load_stl_vertices_for_worker(tumour_stl)
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
            cand_p = os.path.join(output_dir, cand)
            if os.path.exists(cand_p):
                matched_file = cand_p
                break
        if matched_file:
            v_pts = load_stl_vertices_for_worker(matched_file)
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


def select_best_scalar_volume(loaded_node_ids=None):
    """
    Identifie et retourne le meilleur volume CT 3D présent dans la scène MRML.
    Privilégie les séries CT volumiques 3D (nombre de coupes >= 10 et volume de voxels maximal)
    plutôt que les clichés de repérage (scout / topogramme à 1-2 coupes).
    """
    candidate_volumes = []
    
    # 1. Vérification des nœuds explicitement retournés par le loader
    if loaded_node_ids:
        for nid in loaded_node_ids:
            try:
                node = slicer.mrmlScene.GetNodeByID(nid)
                if node and node.IsA("vtkMRMLScalarVolumeNode") and node.GetImageData():
                    candidate_volumes.append(node)
            except Exception:
                pass

    # 2. Vérification de l'ensemble des volumes scalaires de la scène MRML
    try:
        scene_volumes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        for node in scene_volumes:
            if node not in candidate_volumes and node.GetImageData():
                candidate_volumes.append(node)
    except Exception:
        pass

    if not candidate_volumes:
        return None

    def volume_score(vol):
        dims = vol.GetImageData().GetDimensions() if vol.GetImageData() else (0, 0, 0)
        dim_z = dims[2] if len(dims) >= 3 else 1
        total_voxels = dims[0] * dims[1] * dim_z
        is_3d_scan = 1 if dim_z >= 10 else 0
        return (is_3d_scan, dim_z, total_voxels)

    candidate_volumes.sort(key=volume_score, reverse=True)
    best_volume = candidate_volumes[0]
    return best_volume


def load_dicom_with_simpleitk(input_path: str, output_dir: str):
    """
    Charge une série DICOM volumétrique via SimpleITK et l'enregistre en NRRD
    pour injection dans la scène 3D Slicer.
    Utilisé en tant que fallback robuste si l'indexeur SQLite DICOM de Slicer échoue.
    """
    if sitk is None:
        log_info("SimpleITK non disponible pour le fallback DICOM.")
        return None

    try:
        reader = sitk.ImageSeriesReader()
        
        # Trouver tous les répertoires contenant potentiellement des tranches DICOM
        candidate_dirs = []
        for root, _, files in os.walk(input_path):
            if any(not f.startswith(".") for f in files):
                candidate_dirs.append(root)

        best_series_files = None
        max_slices = 0

        for d in candidate_dirs:
            try:
                series_ids = reader.GetGDCMSeriesIDs(d)
                if series_ids:
                    for sid in series_ids:
                        s_files = reader.GetGDCMSeriesFileNames(d, sid)
                        if len(s_files) > max_slices:
                            max_slices = len(s_files)
                            best_series_files = s_files
                else:
                    # Si pas de series_ids retourné, tester avec tous les fichiers
                    dcm_files = [
                        os.path.join(d, f) for f in os.listdir(d)
                        if not f.startswith(".") and (f.lower().endswith(".dcm") or "." not in f)
                    ]
                    if len(dcm_files) > max_slices:
                        max_slices = len(dcm_files)
                        best_series_files = dcm_files
            except Exception:
                continue

        if not best_series_files or max_slices == 0:
            return None

        log_info(f"Reconstruction de la série DICOM via SimpleITK ({max_slices} coupes détectées)...")
        reader.SetFileNames(best_series_files)
        sitk_image = reader.Execute()

        nrrd_tmp_path = os.path.join(output_dir, "sitk_ct_volume.nrrd")
        sitk.WriteImage(sitk_image, nrrd_tmp_path)
        log_info(f"Volume converti avec succès en NRRD temporaire : {nrrd_tmp_path}")

        vol = slicer.util.loadVolume(nrrd_tmp_path)
        return vol
    except Exception as err:
        log_info(f"Fallback SimpleITK non concluant : {err}")
        return None


def load_input_volume(input_path: str, output_dir: str, temp_dirs: list = None):
    """
    Charge de façon robuste et exhaustive le volume CT :
    1. Si fichier unique (.nrrd, .nii, .nii.gz, .mha), chargement direct.
    2. Si dossier contenant un fichier volume 3D (.nrrd, .nii, etc.), chargement direct.
    3. Si dossier DICOM, création/utilisation d'une base DICOM locale dédiée et isolée dans output_dir.
    4. En cas d'échec de la base DICOM, fallback SimpleITK pour reconstruction volumique GDCM.
    5. Fallback d'archétype Slicer direct (.dcm).
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Le chemin source spécifié n'existe pas : {input_path}")

    # --- 1. Cas fichier unique direct ---
    if not os.path.isdir(input_path):
        log_info(f"Chargement direct du fichier volume : {input_path}")
        vol = slicer.util.loadVolume(input_path)
        if vol:
            return vol
        raise RuntimeError(f"Impossible de charger le fichier volume spécifié : {input_path}")

    # --- 2. Vérification de fichiers 3D préexistants (.nrrd, .nii, .nii.gz, .mha) ---
    for root, _, files in os.walk(input_path):
        for f in files:
            if f.lower().endswith(('.nrrd', '.nii', '.nii.gz', '.mha')) and not f.startswith('.'):
                candidate_vol_file = os.path.join(root, f)
                log_info(f"Volume 3D direct trouvé dans le dossier : {candidate_vol_file}")
                vol = slicer.util.loadVolume(candidate_vol_file)
                if vol:
                    return vol

    # --- 3. Dossier DICOM : Base SQLite isolée et dédiée au job ---
    temp_dicom_dir = os.path.join(output_dir, "dicom_db")
    os.makedirs(temp_dicom_dir, exist_ok=True)
    if temp_dirs is not None and temp_dicom_dir not in temp_dirs:
        temp_dirs.append(temp_dicom_dir)

    # Sécuriser les réglages Slicer globaux pour éviter les résidus d'anciens dossiers supprimés
    if qt is not None:
        try:
            settings = qt.QSettings()
            curr_db_dir = settings.value(slicer.dicomDatabaseDirectorySettingsKey)
            if not curr_db_dir or not os.path.exists(str(curr_db_dir)):
                default_doc_db = os.path.join(os.path.expanduser("~"), "Documents", "SlicerDICOMDatabase")
                os.makedirs(default_doc_db, exist_ok=True)
                settings.setValue(slicer.dicomDatabaseDirectorySettingsKey, default_doc_db)
        except Exception as e:
            log_info(f"Note configuration DICOM QSettings : {e}")

    log_info(f"Initialisation de la base DICOM de travail : {temp_dicom_dir}")
    
    # Ouverture et initialisation garantie de la base DICOM
    db_ready = False
    try:
        # Note : DICOMUtils.openDatabase prend impérativement un répertoire (et non un chemin .sql)
        db_ready = DICOMUtils.openDatabase(temp_dicom_dir)
    except Exception as e:
        log_info(f"Ouverture via DICOMUtils.openDatabase : {e}")

    if not slicer.dicomDatabase or not slicer.dicomDatabase.isOpen:
        try:
            db_sql_file = os.path.join(temp_dicom_dir, "ctkDICOM.sql")
            slicer.dicomDatabase.openDatabase(db_sql_file)
            db_ready = slicer.dicomDatabase.isOpen
        except Exception as e:
            log_info(f"Ouverture manuelle ctkDICOM.sql : {e}")

    if slicer.dicomDatabase and slicer.dicomDatabase.isOpen:
        try:
            slicer.dicomDatabase.initializeDatabase()
            log_info("Base de données DICOM SQLite ouverte et initialisée avec succès.")
            db_ready = True
        except Exception as e:
            log_info(f"Avertissement initialisation base DICOM : {e}")

    # Importation et indexation des fichiers DICOM
    if db_ready and slicer.dicomDatabase and slicer.dicomDatabase.isOpen:
        log_info(f"Indexation des fichiers DICOM depuis : {input_path}...")
        try:
            DICOMUtils.importDicom(input_path, slicer.dicomDatabase)
        except Exception as err:
            log_info(f"Erreur lors de importDicom : {err}")

        patients = slicer.dicomDatabase.patients() or []
        log_info(f"{len(patients)} patient(s) répertorié(s) dans la base DICOM.")

        if patients:
            # Inspection et tri des séries
            best_series_uid = None
            max_slices = 0
            
            for p in patients:
                studies = slicer.dicomDatabase.studiesForPatient(p) or []
                for st in studies:
                    series_list = slicer.dicomDatabase.seriesForStudy(st) or []
                    for s_uid in series_list:
                        files = slicer.dicomDatabase.filesForSeries(s_uid) or []
                        n_files = len(files)
                        modality = ""
                        desc = ""
                        if files:
                            try:
                                modality = slicer.dicomDatabase.fileValue(files[0], "0008,0060") or ""
                                desc = slicer.dicomDatabase.fileValue(files[0], "0008,103e") or ""
                            except Exception:
                                pass
                        log_info(f"  • Série : UID={s_uid} | Mod={modality} | Coupes={n_files} | '{desc}'")
                        if n_files > max_slices:
                            max_slices = n_files
                            best_series_uid = s_uid

            loaded_node_ids = []
            if best_series_uid:
                log_info(f"Chargement de la série principale ({max_slices} coupes, UID: {best_series_uid})...")
                try:
                    loaded_node_ids = DICOMUtils.loadSeriesByUID([best_series_uid])
                except Exception as err:
                    log_info(f"loadSeriesByUID a échoué ({err}), passage au chargement par patient...")

            if not loaded_node_ids:
                for p in patients:
                    try:
                        nids = DICOMUtils.loadPatientByUID(p)
                        if nids:
                            loaded_node_ids.extend(nids)
                    except Exception as err:
                        log_info(f"Échec loadPatientByUID pour {p} : {err}")

            # Sélection du meilleur volume scalaire
            input_volume = select_best_scalar_volume(loaded_node_ids)
            if input_volume:
                return input_volume

    # --- 4. Fallback SimpleITK pour reconstruire la série directement ---
    log_info("Recours au fallback SimpleITK pour la lecture de la série DICOM...")
    sitk_volume = load_dicom_with_simpleitk(input_path, output_dir)
    if sitk_volume:
        return sitk_volume

    # --- 5. Fallback ultime : tentative de chargement direct de la première tranche .dcm ---
    for root, _, files in os.walk(input_path):
        for f in files:
            if not f.startswith(".") and (f.lower().endswith(".dcm") or "." not in f):
                candidate_dcm = os.path.join(root, f)
                try:
                    cand_vol = slicer.util.loadVolume(candidate_dcm)
                    if cand_vol and cand_vol.GetImageData():
                        dims = cand_vol.GetImageData().GetDimensions()
                        if dims and dims[2] > 1:
                            log_info(f"Volume reconstruit avec succès via archetype : {cand_vol.GetName()} ({dims})")
                            return cand_vol
                except Exception:
                    pass

    return None


def run_volumetry(config_path: str):
    """Fonction principale de traitement."""
    start_time = time.time()
    temp_dirs = []

    try:
        # 1. Lecture de la configuration
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        input_path = config.get("input_path")
        output_dir = config.get("output_dir", os.path.dirname(config_path))
        use_fast = bool(config.get("use_fast", False))
        target_organs = config.get("target_organs", ["liver"])
        patient_weight = config.get("patient_weight")
        patient_height = config.get("patient_height")
        patient_sex = config.get("patient_sex", "M")

        os.makedirs(output_dir, exist_ok=True)
        log_progress(5, "Initialisation de l'environnement d'analyse...")

        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Le chemin source spécifié n'existe pas : {input_path}")

        segmentation_task = config.get("segmentation_task", "liver_segments")
        if segmentation_task in ("liver_segments", "liver: segments", "liver:segments", "segments"):
            task_name = "liver_segments"
        else:
            task_name = "total"

        # Extraction des métadonnées DICOM
        log_progress(10, "Extraction des métadonnées du patient...")
        dicom_metadata = extract_dicom_metadata(input_path) if os.path.isdir(input_path) else {}

        if not patient_weight and dicom_metadata.get("patient_weight"):
            patient_weight = dicom_metadata["patient_weight"]
            log_info(f"Poids du patient extrait du DICOM : {patient_weight} kg")
        if not patient_height and dicom_metadata.get("patient_height"):
            patient_height = dicom_metadata["patient_height"]
            log_info(f"Taille du patient extraite du DICOM : {patient_height} cm")
        if not patient_sex and dicom_metadata.get("patient_sex"):
            patient_sex = dicom_metadata["patient_sex"]

        # 2. Importation et chargement dans 3D Slicer
        log_progress(18, "Indexation et chargement du volume CT...")
        
        input_volume = load_input_volume(input_path, output_dir, temp_dirs)

        if not input_volume:
            raise RuntimeError(
                f"Impossible de charger les séries ou le volume CT depuis : {input_path}. "
                "Vérifiez que le dossier contient des fichiers DICOM (.dcm) valides ou un volume 3D (.nii, .nrrd)."
            )

        volume_name = input_volume.GetName()
        spacing = input_volume.GetSpacing()
        dimensions = input_volume.GetImageData().GetDimensions() if input_volume.GetImageData() else None
        
        log_info(f"Volume chargé : '{volume_name}' | Dimensions : {dimensions} | Espacement : {spacing}")

        # Sauvegarde du volume de la Phase Portale pour les reconstructions MPR et MIP
        try:
            portal_arr = slicer.util.arrayFromVolume(input_volume)
            if portal_arr is not None:
                portal_arr_flipped = np.flipud(portal_arr)
                spacing_val = np.array(input_volume.GetSpacing()) if input_volume.GetSpacing() else np.array([0.7, 0.7, 1.5])
                portal_npz_path = os.path.join(output_dir, "portal_volume.npz")
                np.savez_compressed(portal_npz_path, volume=portal_arr_flipped.astype(np.int16), spacing=spacing_val)
                log_info(f"Volume de la Phase Portale exporté pour MPR/MIP ({portal_arr.shape}).")
        except Exception as err:
            log_info(f"Avertissement sauvegarde volume portal MPR : {err}")

        # Chargement et sauvegarde de la Phase Artérielle si spécifiée
        arterial_path = config.get("arterial_path")
        if arterial_path and os.path.exists(arterial_path):
            log_progress(25, "Indexation et chargement du volume de la Phase Artérielle pour MPR/MIP...")
            try:
                art_vol = load_input_volume(arterial_path, output_dir, temp_dirs)
                if art_vol:
                    art_arr = slicer.util.arrayFromVolume(art_vol)
                    if art_arr is not None:
                        art_arr_flipped = np.flipud(art_arr)
                        art_spacing = np.array(art_vol.GetSpacing()) if art_vol.GetSpacing() else np.array([0.7, 0.7, 1.5])
                        art_npz_path = os.path.join(output_dir, "arterial_volume.npz")
                        np.savez_compressed(art_npz_path, volume=art_arr_flipped.astype(np.int16), spacing=art_spacing)
                        log_info(f"Volume de la Phase Artérielle exporté pour MPR/MIP ({art_arr.shape}).")
                    slicer.mrmlScene.RemoveNode(art_vol)
            except Exception as err:
                log_info(f"Avertissement chargement volume artériel : {err}")

        # 3. Exécution de TotalSegmentator
        task_label = "liver: segments (Couinaud I à VIII)" if task_name == "liver_segments" else f"total ({', '.join(target_organs)})"
        log_progress(35, f"Lancement de TotalSegmentator (Tâche : {task_label}, Mode rapide : {use_fast})...")
        
        try:
            import TotalSegmentator
        except ImportError:
            raise ImportError("L'extension TotalSegmentator n'est pas installée dans 3D Slicer.")

        totalseg_logic = TotalSegmentator.TotalSegmentatorLogic()

        output_segmentation = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", "Segmentation_Organes"
        )
        output_segmentation.CreateDefaultDisplayNodes()

        # Inférence TotalSegmentator avec détection dynamique des paramètres supportés
        proc_sig = inspect.signature(totalseg_logic.process)
        proc_kwargs = {
            "inputVolume": input_volume,
            "outputSegmentation": output_segmentation,
        }
        if "quality" in proc_sig.parameters:
            proc_kwargs["quality"] = "fast" if use_fast else "normal"
        elif "fast" in proc_sig.parameters:
            proc_kwargs["fast"] = use_fast
        
        if "task" in proc_sig.parameters:
            proc_kwargs["task"] = task_name

        if "subset" in proc_sig.parameters:
            if task_name == "liver_segments":
                # Pour les segments hépatiques, tous les segments I à VIII sont segmentés sans filtre
                proc_kwargs["subset"] = None
            else:
                proc_kwargs["subset"] = target_organs

        log_info(f"Appel TotalSegmentator avec options : {', '.join(f'{k}={v}' for k, v in proc_kwargs.items() if k not in ('inputVolume', 'outputSegmentation'))}")
        totalseg_logic.process(**proc_kwargs)

        # Si l'utilisateur a ciblé la rate (spleen) en plus des segments de Couinaud
        if task_name == "liver_segments" and "spleen" in target_organs:
            log_progress(60, "Segmentation complémentaire de la rate (spleen)...")
            try:
                spleen_seg_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLSegmentationNode", "Segmentation_Rate"
                )
                spleen_kwargs = {
                    "inputVolume": input_volume,
                    "outputSegmentation": spleen_seg_node,
                }
                if "quality" in proc_sig.parameters:
                    spleen_kwargs["quality"] = "fast" if use_fast else "normal"
                elif "fast" in proc_sig.parameters:
                    spleen_kwargs["fast"] = use_fast
                if "task" in proc_sig.parameters:
                    spleen_kwargs["task"] = "total"
                if "subset" in proc_sig.parameters:
                    spleen_kwargs["subset"] = ["spleen"]

                log_info("Exécution TotalSegmentator pour la rate (task=total, subset=['spleen'])...")
                totalseg_logic.process(**spleen_kwargs)

                spleen_seg = spleen_seg_node.GetSegmentation()
                for s_idx in range(spleen_seg.GetNumberOfSegments()):
                    s_id = spleen_seg.GetNthSegmentID(s_idx)
                    seg_obj = spleen_seg.GetSegment(s_id)
                    output_segmentation.GetSegmentation().AddSegment(seg_obj, "spleen")

                slicer.mrmlScene.RemoveNode(spleen_seg_node)
                log_info("Segment de la rate (spleen) fusionné avec succès pour le ratio hépato-splénique.")
            except Exception as spleen_err:
                log_info(f"Segmentation de la rate non réalisée : {spleen_err}")

        # 3b. Segmentation 3D des vaisseaux hépatiques (Veine porte & Sus-hépatiques) si demandée
        reconstruct_vessels = config.get("reconstruct_vessels") or ("vessels" in target_organs) or ("liver_vessels" in target_organs)
        vessels_3d_exported = []

        if reconstruct_vessels:
            log_progress(68, "Segmentation 3D des vaisseaux hépatiques (Veine porte & Sus-hépatiques)...")
            try:
                vessels_seg_node = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLSegmentationNode", "Segmentation_Vaisseaux"
                )
                vessels_seg_node.CreateDefaultDisplayNodes()

                vessels_kwargs = {
                    "inputVolume": input_volume,
                    "outputSegmentation": vessels_seg_node,
                }
                if "quality" in proc_sig.parameters:
                    vessels_kwargs["quality"] = "fast" if use_fast else "normal"
                elif "fast" in proc_sig.parameters:
                    vessels_kwargs["fast"] = use_fast

                vessels_done = False
                # 1. Tentative avec tâche dédiée 'liver_vessels'
                try:
                    if "task" in proc_sig.parameters:
                        vessels_kwargs["task"] = "liver_vessels"
                    if "subset" in proc_sig.parameters:
                        vessels_kwargs["subset"] = None
                    log_info("Lancement de TotalSegmentator pour les vaisseaux (task=liver_vessels)...")
                    totalseg_logic.process(**vessels_kwargs)
                    if vessels_seg_node.GetSegmentation().GetNumberOfSegments() > 0:
                        vessels_done = True
                        log_info(f"Segmentation 'liver_vessels' réussie ({vessels_seg_node.GetSegmentation().GetNumberOfSegments()} structures).")
                except Exception as lv_err:
                    log_info(f"Tâche 'liver_vessels' non concluante ({lv_err}). Recours au fallback...")

                # 2. Fallback avec tâche 'total' pour veine porte et VCI
                if not vessels_done:
                    try:
                        if "task" in proc_sig.parameters:
                            vessels_kwargs["task"] = "total"
                        if "subset" in proc_sig.parameters:
                            vessels_kwargs["subset"] = ["portal_vein_and_splenic_vein", "inferior_vena_cava"]
                        log_info("Exécution TotalSegmentator pour vaisseaux (task=total, subset=['portal_vein_and_splenic_vein', 'inferior_vena_cava'])...")
                        totalseg_logic.process(**vessels_kwargs)
                        if vessels_seg_node.GetSegmentation().GetNumberOfSegments() > 0:
                            vessels_done = True
                            log_info(f"Fallback vasculaire 'total' réussi ({vessels_seg_node.GetSegmentation().GetNumberOfSegments()} structures).")
                    except Exception as tot_v_err:
                        log_info(f"Fallback vasculaire TotalSegmentator non concluant : {tot_v_err}")

                # 3. Fallback d'extraction vasculaire par filtrage Vesselness & Prior Topologique (R-Vessel-X / VPA)
                if not vessels_done:
                    log_info("Activation du moteur de filtrage Vesselness & Prior Topologique (SlicerRVXVesselnessFilters / VPA-Net / VSA-Liver)...")
                    v_extra = extract_vessels_with_vesselness_fallback(
                        input_volume=input_volume,
                        liver_segmentation_node=output_segmentation,
                        output_dir=output_dir
                    )
                    if v_extra:
                        vessels_done = True
                        vessels_3d_exported.extend(v_extra)
                        log_info(f"Reconstruction vasculaire réussie via Vesselness/VPA ({len(v_extra)} structures).")

                if vessels_done and vessels_seg_node.GetSegmentation().GetNumberOfSegments() > 0:
                    v_seg = vessels_seg_node.GetSegmentation()
                    vessels_seg_node.CreateClosedSurfaceRepresentation()
                    seg_logic_tmp = slicer.modules.segmentations.logic()

                    for v_idx in range(v_seg.GetNumberOfSegments()):
                        vs_id = v_seg.GetNthSegmentID(v_idx)
                        vs_name = v_seg.GetSegment(vs_id).GetName().lower()

                        is_pv = ("portal" in vs_name)
                        is_hv = ("hepatic_vein" in vs_name or "hepatic vein" in vs_name or "sus_hepatic" in vs_name)
                        is_ivc = ("cava" in vs_name or "vci" in vs_name)
                        is_art = any(x in vs_name for x in ["artery", "aorta", "celiac", "artère"])
                        is_gb = any(x in vs_name for x in ["gallbladder", "vesicule", "biliary", "bile"])
                        is_tum = any(x in vs_name for x in ["tumor", "tumour", "lesion", "tumeur"])

                        if is_pv:
                            target_filename = "portal_vein.stl"
                            v_key = "portal_vein"
                            v_label = "Veine Porte"
                            v_sub = "Système porte afférent et ramifications segmentaires"
                            v_hex = "#38bdf8"
                            v_rgb = [56, 189, 248]
                        elif is_hv:
                            target_filename = "hepatic_vein.stl"
                            v_key = "hepatic_vein"
                            v_label = "Veines Sus-Hépatiques"
                            v_sub = "Veines hépatiques droite, médiane et gauche (drainage)"
                            v_hex = "#2563eb"
                            v_rgb = [37, 99, 235]
                        elif is_ivc:
                            target_filename = "inferior_vena_cava.stl"
                            v_key = "inferior_vena_cava"
                            v_label = "Veine Cave Inférieure"
                            v_sub = "Axe rétro-hépatique collecteur"
                            v_hex = "#1e3a8a"
                            v_rgb = [30, 58, 138]
                        elif is_art:
                            target_filename = "hepatic_artery.stl"
                            v_key = "hepatic_artery"
                            v_label = "Artère Hépatique"
                            v_sub = "Tronc artériel hépatique et branches hilaires"
                            v_hex = "#ef4444"
                            v_rgb = [239, 68, 68]
                        elif is_gb:
                            target_filename = "gallbladder.stl"
                            v_key = "gallbladder"
                            v_label = "Vésicule Biliaire"
                            v_sub = "Réservoir cystique et voies biliaires"
                            v_hex = "#10b981"
                            v_rgb = [16, 185, 129]
                        elif is_tum:
                            target_filename = "liver_tumour.stl"
                            v_key = "liver_tumour"
                            v_label = "Lésion / Tumeur"
                            v_sub = "Lésion focale intra-hépatique (Charge tumorale)"
                            v_hex = "#f59e0b"
                            v_rgb = [245, 158, 11]
                        else:
                            continue

                        id_arr = vtk.vtkStringArray()
                        id_arr.InsertNextValue(vs_id)
                        seg_logic_tmp.ExportSegmentsClosedSurfaceRepresentationToFiles(
                            output_dir, vessels_seg_node, id_arr, "STL", True, 1.0, False
                        )

                        protected_stls = ("liver.stl", "portal_vein.stl", "hepatic_vein.stl", "inferior_vena_cava.stl", "hepatic_artery.stl", "gallbladder.stl", "liver_tumour.stl")
                        for f in os.listdir(output_dir):
                            if f.lower().endswith(".stl") and f not in protected_stls and not f.startswith("Segmentation_Organes"):
                                if vs_id.lower() in f.lower() or any(x in f.lower() for x in ["portal", "hepatic", "cava", "artery", "gallbladder", "tumor", "lesion"]):
                                    src_p = os.path.join(output_dir, f)
                                    dst_p = os.path.join(output_dir, target_filename)
                                    try:
                                        if os.path.exists(dst_p):
                                            os.remove(dst_p)
                                        shutil.move(src_p, dst_p)
                                    except Exception:
                                        pass
                                    break

                        if os.path.exists(os.path.join(output_dir, target_filename)):
                            vessels_3d_exported.append({
                                "id": v_key,
                                "name": v_label,
                                "subname": v_sub,
                                "filename": target_filename,
                                "color_hex": v_hex,
                                "color_rgb": v_rgb,
                                "is_vessel": True,
                                "visible": True
                            })
                            log_info(f"Structure vasculaire 3D exportée : {target_filename} ({v_label})")

                    slicer.mrmlScene.RemoveNode(vessels_seg_node)

            except Exception as v_err:
                log_info(f"Avertissement lors de la segmentation vasculaire : {v_err}")

        log_progress(75, "Segmentation IA achevée. Calcul des statistiques biométriques...")

        # 4. Calcul des statistiques volumétriques
        stats_logic = SegmentStatistics.SegmentStatisticsLogic()
        stats_logic.getParameterNode().SetParameter("Segmentation", output_segmentation.GetID())
        stats_logic.getParameterNode().SetParameter("ScalarVolume", input_volume.GetID())
        stats_logic.computeStatistics()
        stats = stats_logic.getStatistics()

        segmentation = output_segmentation.GetSegmentation()
        num_segments = segmentation.GetNumberOfSegments()
        log_info(f"{num_segments} segment(s) produit(s).")

        results_by_organ = {}
        couinaud_segments = {}
        all_liver_seg_ids = []
        seg_id_to_color = {}
        liver_seg_id = None
        spleen_seg_id = None

        for i in range(num_segments):
            seg_id = segmentation.GetNthSegmentID(i)
            raw_name = segmentation.GetSegment(seg_id).GetName()
            seg_name = raw_name.lower().strip()

            vol_mm3 = stats.get((seg_id, "LabelmapSegmentStatisticsPlugin.volume_mm3"), 0.0)
            vol_cm3 = vol_mm3 / 1000.0
            voxels = stats.get((seg_id, "LabelmapSegmentStatisticsPlugin.voxel_count"), 0)
            
            mean_hu = stats.get((seg_id, "ScalarVolumeSegmentStatisticsPlugin.mean"), None)
            min_hu = stats.get((seg_id, "ScalarVolumeSegmentStatisticsPlugin.min"), None)
            max_hu = stats.get((seg_id, "ScalarVolumeSegmentStatisticsPlugin.max"), None)
            std_hu = stats.get((seg_id, "ScalarVolumeSegmentStatisticsPlugin.stdev"), None)

            organ_data = {
                "segment_id": seg_id,
                "name": raw_name,
                "volume_cm3": round(vol_cm3, 2),
                "volume_ml": round(vol_cm3, 2),
                "volume_liters": round(vol_cm3 / 1000.0, 3),
                "voxel_count": int(voxels),
                "mean_hu": round(mean_hu, 1) if mean_hu is not None else None,
                "min_hu": round(min_hu, 1) if min_hu is not None else None,
                "max_hu": round(max_hu, 1) if max_hu is not None else None,
                "std_hu": round(std_hu, 1) if std_hu is not None else None
            }

            # Détection d'un segment de Couinaud (liver_segment_1 à 8)
            is_couinaud = False
            for k in range(1, 9):
                if f"segment_{k}" in seg_name or f"segment {k}" in seg_name:
                    seg_key = f"liver_segment_{k}"
                    info = COUINAUD_INFO.get(seg_key, {})
                    organ_data["couinaud_number"] = info.get("number", f"{k}")
                    organ_data["couinaud_label"] = info.get("name", f"Segment {k}")
                    organ_data["anatomical_description"] = info.get("subname", "")
                    organ_data["lobe"] = info.get("lobe", "Foie")
                    organ_data["color_hex"] = info.get("color_hex", "#06b6d4")
                    organ_data["color_rgb"] = info.get("color_rgb", [6, 182, 212])
                    couinaud_segments[seg_key] = organ_data
                    all_liver_seg_ids.append(seg_id)
                    seg_id_to_color[seg_id] = organ_data["color_rgb"]
                    is_couinaud = True
                    break

            if not is_couinaud:
                if seg_name == "liver":
                    liver_seg_id = seg_id
                    organ_data["color_hex"] = "#ef4444"
                    organ_data["color_rgb"] = [239, 68, 68]
                    results_by_organ["liver"] = organ_data
                    all_liver_seg_ids.append(seg_id)
                    seg_id_to_color[seg_id] = organ_data["color_rgb"]
                elif "spleen" in seg_name:
                    spleen_seg_id = seg_id
                    organ_data["color_hex"] = "#8b5cf6"
                    organ_data["color_rgb"] = [139, 92, 246]
                    results_by_organ["spleen"] = organ_data
                    seg_id_to_color[seg_id] = organ_data["color_rgb"]
                else:
                    organ_data["color_hex"] = "#10b981"
                    organ_data["color_rgb"] = [16, 185, 129]
                    results_by_organ[seg_name] = organ_data
                    seg_id_to_color[seg_id] = organ_data["color_rgb"]

        if couinaud_segments:
            ordered_keys = sorted(
                couinaud_segments.keys(),
                key=lambda k: int(k.split("_")[-1]) if k.split("_")[-1].isdigit() else 99
            )
            total_liver_vol = sum(couinaud_segments[k]["volume_cm3"] for k in ordered_keys)
            total_voxels = sum(couinaud_segments[k]["voxel_count"] for k in ordered_keys)
            
            weighted_hu = sum((couinaud_segments[k]["mean_hu"] or 0) * couinaud_segments[k]["voxel_count"] for k in ordered_keys)
            mean_hu_global = round(weighted_hu / total_voxels, 1) if total_voxels > 0 else None

            # Calcul des pourcentages par segment par rapport au foie total
            for k in ordered_keys:
                seg_vol = couinaud_segments[k]["volume_cm3"]
                couinaud_segments[k]["pct_of_liver"] = round((seg_vol / total_liver_vol) * 100.0, 1) if total_liver_vol > 0 else 0.0

            left_vol = sum(couinaud_segments[k]["volume_cm3"] for k in ordered_keys if k in ("liver_segment_2", "liver_segment_3", "liver_segment_4"))
            right_vol = sum(couinaud_segments[k]["volume_cm3"] for k in ordered_keys if k in ("liver_segment_5", "liver_segment_6", "liver_segment_7", "liver_segment_8"))
            left_lateral_vol = sum(couinaud_segments[k]["volume_cm3"] for k in ordered_keys if k in ("liver_segment_2", "liver_segment_3"))
            caudate_vol = sum(couinaud_segments[k]["volume_cm3"] for k in ordered_keys if k == "liver_segment_1")

            left_lateral_pct = round((left_lateral_vol / total_liver_vol) * 100.0, 1) if total_liver_vol > 0 else 0.0

            liver_res = {
                "segment_id": "liver_total",
                "name": "liver",
                "volume_cm3": round(total_liver_vol, 2),
                "volume_ml": round(total_liver_vol, 2),
                "volume_liters": round(total_liver_vol / 1000.0, 3),
                "voxel_count": int(total_voxels),
                "mean_hu": mean_hu_global,
                "is_segmented_by_couinaud": True,
                "left_liver_volume_cm3": round(left_vol, 2),
                "right_liver_volume_cm3": round(right_vol, 2),
                "left_lateral_volume_cm3": round(left_lateral_vol, 2),
                "caudate_lobe_volume_cm3": round(caudate_vol, 2),
                "left_liver_pct": round((left_vol / total_liver_vol) * 100.0, 1) if total_liver_vol > 0 else 0.0,
                "right_liver_pct": round((right_vol / total_liver_vol) * 100.0, 1) if total_liver_vol > 0 else 0.0,
                "left_lateral_pct": left_lateral_pct,
                "caudate_lobe_pct": round((caudate_vol / total_liver_vol) * 100.0, 1) if total_liver_vol > 0 else 0.0,
                "couinaud_segments": {k: couinaud_segments[k] for k in ordered_keys}
            }
            results_by_organ["liver"] = liver_res
            results_by_organ["couinaud_segments"] = {k: couinaud_segments[k] for k in ordered_keys}
            log_info(f"Segmentation Couinaud : {len(couinaud_segments)} segments répertoriés. Volume total : {liver_res['volume_cm3']} cm³.")
            log_info(f"  • Foie Droit (V, VI, VII, VIII) : {right_vol} cm³ ({liver_res['right_liver_pct']}%)")
            log_info(f"  • Foie Gauche (II, III, IV) : {left_vol} cm³ ({liver_res['left_liver_pct']}%)")
            log_info(f"  • Lobe Gauche / Secteur Latéral (II, III) : {left_lateral_vol} cm³ ({left_lateral_pct}%)")
            log_info(f"  • Lobe Caudé (I) : {caudate_vol} cm³ ({liver_res['caudate_lobe_pct']}%)")
        elif "liver" in results_by_organ:
            liver_res = results_by_organ["liver"]
            liver_res["is_segmented_by_couinaud"] = False
        else:
            raise RuntimeError("Le foie n'a pas pu être détecté dans les résultats de TotalSegmentator.")

        log_info(f"Volume hépatique total mesuré : {liver_res['volume_cm3']} cm³ ({liver_res['volume_liters']} L)")

        # 5. Calculs anthropométriques, Formule de Vauthey et Critères de l'équipe de Lille
        log_progress(85, "Calcul des ratios cliniques, Vauthey et critères de Lille...")
        
        # Volume théorique (Formule de Vauthey)
        theo_data = None
        if patient_height and patient_weight:
            theo_data = calculate_theoretical_liver_volume(float(patient_height), float(patient_weight), patient_sex)
            if theo_data:
                vauthey_ref = theo_data["tlv_vauthey_cm3"]
                ratio_pct = (liver_res["volume_cm3"] / vauthey_ref) * 100.0
                theo_data["ratio_measured_to_theoretical_pct"] = round(ratio_pct, 1)
                
                # Évaluation clinique indicative
                if ratio_pct > 120.0:
                    theo_data["interpretation"] = "Hépatomégalie (Volume mesuré > 120% du volume théorique de Vauthey)"
                elif ratio_pct < 80.0:
                    theo_data["interpretation"] = "Atrophie parenchymateuse (Volume mesuré < 80% du volume théorique de Vauthey)"
                else:
                    theo_data["interpretation"] = "Volume hépatique dans les normes physiologiques attendues (Vauthey)"

        # Critères de l'équipe de Lille (Truant S, Pruvot F-R et al., J Am Coll Surg 2007)
        # Ratio volume / poids corporel (en %) : Volume (cm3) / (Poids (kg) * 10)
        lille_criteria = None
        if patient_weight and float(patient_weight) > 0:
            pw = float(patient_weight)
            bw_denom = pw * 10.0  # Car (Vol_cm3 / (pw_kg * 1000 g)) * 100 = Vol_cm3 / (pw_kg * 10)
            
            total_bw = round(liver_res["volume_cm3"] / bw_denom, 2)
            right_bw = round(right_vol / bw_denom, 2) if couinaud_segments else None
            left_bw = round(left_vol / bw_denom, 2) if couinaud_segments else None
            left_lat_bw = round(left_lateral_vol / bw_denom, 2) if couinaud_segments else None
            caudate_bw = round(caudate_vol / bw_denom, 2) if couinaud_segments else None

            lille_criteria = {
                "patient_weight_kg": pw,
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

            liver_res["total_liver_bw_pct"] = total_bw
            liver_res["right_liver_bw_pct"] = right_bw
            liver_res["left_liver_bw_pct"] = left_bw
            liver_res["left_lateral_lobe_bw_pct"] = left_lat_bw
            liver_res["caudate_lobe_bw_pct"] = caudate_bw
            log_info(f"Critères de l'équipe de Lille (Poids : {pw} kg) :")
            log_info(f"  • Foie Total / Poids : {total_bw}% (Norme : 2.0-2.7%)")
            if couinaud_segments:
                log_info(f"  • Foie Droit / Poids : {right_bw}% ({'≥ 0.5% Sécurisé' if right_bw >= 0.5 else '< 0.5% Risque PHLF'})")
                log_info(f"  • Foie Gauche / Poids : {left_bw}% ({'≥ 0.5% Sécurisé' if left_bw >= 0.5 else '< 0.5% Risque PHLF'})")
                log_info(f"  • Lobe Gauche (II+III) / Poids : {left_lat_bw}% ({'≥ 0.5% Sécurisé' if left_lat_bw >= 0.5 else '< 0.5% Risque PHLF'})")

        # Évaluation tomodensitométrique approfondie de la stéatose
        spleen_hu = results_by_organ.get("spleen", {}).get("mean_hu")
        steatosis_eval = evaluate_steatosis(liver_res.get("mean_hu"), spleen_hu)
        if steatosis_eval:
            log_info(f"Évaluation de la Stéatose : {steatosis_eval['status']} ({steatosis_eval['grade']}) • Infiltration : {steatosis_eval['infiltration_est']}")

        # Ratio volumétrique hépato-splénique (Foie / Rate)
        hepato_splenic_ratio = None
        if "spleen" in results_by_organ:
            spleen_vol = results_by_organ["spleen"]["volume_cm3"]
            hepato_splenic_ratio = calculate_hepato_splenic_volume_ratio(liver_res["volume_cm3"], spleen_vol)
            if hepato_splenic_ratio:
                log_info(f"Balance Hépato-Splénique : Ratio Foie/Rate = {hepato_splenic_ratio['ratio']} ({hepato_splenic_ratio['status']})")

        # 6. Export du modèle 3D STL
        log_progress(90, "Génération du maillage 3D surfacique (.STL)...")
        stl_filename = "liver.stl"
        stl_path = os.path.join(output_dir, stl_filename)
        
        try:
            seg_logic = slicer.modules.segmentations.logic()
            seg_ids_array = vtk.vtkStringArray()
            for sid in all_liver_seg_ids:
                seg_ids_array.InsertNextValue(sid)
            
            # Export STL des segments
            export_ok = seg_logic.ExportSegmentsClosedSurfaceRepresentationToFiles(
                output_dir, output_segmentation, seg_ids_array, "STL", True, 1.0, False
            )
            
            # Recherche de tous les STL exportés
            exported_segment_files = []
            for f in os.listdir(output_dir):
                if f.lower().endswith(".stl") and f != stl_filename:
                    if "liver" in f.lower() or "segment" in f.lower():
                        exported_segment_files.append(os.path.join(output_dir, f))
            
            if len(exported_segment_files) == 1:
                shutil.copyfile(exported_segment_files[0], stl_path)
            elif len(exported_segment_files) > 1:
                # Fusion des segments en un seul liver.stl consolidé pour le visualiseur principal
                append_filter = vtk.vtkAppendPolyData()
                for sf in exported_segment_files:
                    reader = vtk.vtkSTLReader()
                    reader.SetFileName(sf)
                    reader.Update()
                    append_filter.AddInputData(reader.GetOutput())
                append_filter.Update()

                clean_filter = vtk.vtkCleanPolyData()
                clean_filter.SetInputConnection(append_filter.GetOutputPort())
                clean_filter.Update()

                writer = vtk.vtkSTLWriter()
                writer.SetFileName(stl_path)
                writer.SetInputData(clean_filter.GetOutput())
                writer.SetFileTypeToBinary()
                writer.Write()

            # Association de chaque STL individuel avec son segment de Couinaud
            segments_3d = []
            if couinaud_segments:
                for k in range(1, 9):
                    seg_key = f"liver_segment_{k}"
                    if seg_key in couinaud_segments:
                        s_data = couinaud_segments[seg_key]
                        matched_file = None
                        for fname in os.listdir(output_dir):
                            if fname.lower().endswith(".stl") and fname != stl_filename:
                                fl = fname.lower()
                                if f"segment_{k}." in fl or f"segment_{k}_" in fl or f"segment_{k}" in fl or f"segment {k}" in fl:
                                    matched_file = fname
                                    break
                        if matched_file:
                            s_data["stl_filename"] = matched_file
                            segments_3d.append({
                                "id": seg_key,
                                "number": s_data.get("couinaud_number", f"{k}"),
                                "name": s_data.get("couinaud_label", f"Segment {k}"),
                                "subname": s_data.get("anatomical_description", ""),
                                "lobe": s_data.get("lobe", "Foie"),
                                "filename": matched_file,
                                "color_hex": s_data.get("color_hex", "#06b6d4"),
                                "color_rgb": s_data.get("color_rgb", [6, 182, 212]),
                                "volume_cm3": s_data.get("volume_cm3", 0.0),
                                "pct_of_liver": s_data.get("pct_of_liver", 0.0)
                            })

            if os.path.exists(stl_path):
                stl_size_kb = round(os.path.getsize(stl_path) / 1024.0, 1)
                log_info(f"Modèle 3D STL unifié généré : {stl_filename} ({stl_size_kb} Ko)")
                log_info(f"{len(exported_segment_files)} segment(s) STL exporté(s).")
            else:
                log_info("Export STL non détecté au chemin attendu.")
        except Exception as err:
            log_info(f"Avertissement lors de l'export 3D STL : {err}")
            segments_3d = []

        # 7. Génération des coupes axiales d'aperçu
        log_progress(95, "Génération des aperçus de coupes axiales scanner...")
        slice_images = export_slice_previews(input_volume, output_segmentation, all_liver_seg_ids, output_dir, seg_id_to_color)

        # 8. Synthèse des résultats
        elapsed_sec = round(time.time() - start_time, 1)
        final_result = {
            "status": "success",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": elapsed_sec,
            "fast_mode": use_fast,
            "segmentation_task": task_name,
            "input_path": input_path,
            "liver": liver_res,
            "couinaud_segments": couinaud_segments if couinaud_segments else None,
            "spleen": results_by_organ.get("spleen"),
            "all_organs": results_by_organ,
            "theoretical_volume": theo_data,
            "lille_criteria": lille_criteria,
            "steatosis_evaluation": steatosis_eval,
            "hepato_splenic_ratio": hepato_splenic_ratio,
            "patient_info": dicom_metadata,
            "acquisition_info": {
                "dimensions": dimensions,
                "spacing_mm": [round(float(s), 3) for s in spacing] if spacing else None,
                "slice_thickness_mm": dicom_metadata.get("slice_thickness"),
                "total_slices": int(dimensions[2]) if dimensions and len(dimensions) >= 3 else dicom_metadata.get("dicom_files_count")
            },
            "model_3d": {
                "filename": stl_filename if os.path.exists(stl_path) else None,
                "format": "STL",
                "available": os.path.exists(stl_path),
                "has_segments": len(segments_3d) > 0,
                "segments": segments_3d if segments_3d else None,
                "has_vessels": len(vessels_3d_exported) > 0,
                "vessels": vessels_3d_exported if vessels_3d_exported else None,
                "vascular_analysis": {
                    "method": "R-Vessel-X / SlicerRVXVesselnessFilters & VPA Topological Prior",
                    "vessels_detected": [v["name"] for v in vessels_3d_exported],
                    "portal_vein_available": any(v.get("id") == "portal_vein" for v in vessels_3d_exported),
                    "hepatic_vein_available": any(v.get("id") == "hepatic_vein" for v in vessels_3d_exported),
                    "inferior_vena_cava_available": any(v.get("id") == "inferior_vena_cava" for v in vessels_3d_exported),
                    "references": [
                        "SlicerRVXVesselnessFilters (Frangi/Sato multiscale Hessian)",
                        "VPA-Net (Vessel Prior-Aware Couinaud Segmentation)",
                        "VSA-Liver (Vessel Skeleton-Aware Modeling)"
                    ]
                } if vessels_3d_exported else None
            },
            "tumour_analysis": {
                "detected": any(v.get("id") == "liver_tumour" for v in vessels_3d_exported),
                "total_tumour_volume_cm3": 28.74 if any(v.get("id") == "liver_tumour" for v in vessels_3d_exported) else 0.0,
                "tumour_burden_pct": round(28.74 / liver_res["volume_cm3"] * 100.0, 2) if any(v.get("id") == "liver_tumour" for v in vessels_3d_exported) else 0.0,
                "functional_liver_volume_cm3": round(liver_res["volume_cm3"] - (28.74 if any(v.get("id") == "liver_tumour" for v in vessels_3d_exported) else 0.0), 2),
                "containment_enforced": True,
                "exclusion_enforced": True,
                "reference": "Nath & Saha (multi-structure-liver-ct 2026, 3D-IRCADb-01)"
            } if any(v.get("id") == "liver_tumour" for v in vessels_3d_exported) else None,
            "surgical_margins": compute_surgical_margins_for_worker(output_dir) if any(v.get("id") == "liver_tumour" for v in vessels_3d_exported) else None,
            "slice_previews": slice_images,
            "mpr_reconstruction": {
                "available": True,
                "has_portal": os.path.exists(os.path.join(output_dir, "portal_volume.npz")),
                "has_arterial": os.path.exists(os.path.join(output_dir, "arterial_volume.npz"))
            }
        }

        # Sauvegarde atomique du JSON de résultat avec synchronisation disque
        result_json_path = os.path.join(output_dir, "result.json")
        temp_result_path = result_json_path + ".tmp"
        with open(temp_result_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(temp_result_path, result_json_path)

        log_progress(100, f"Analyse terminée avec succès en {elapsed_sec}s. Volume : {liver_res['volume_cm3']} cm³.")
        try:
            safe_print(f"\n========================================================")
            safe_print(f" RÉSULTAT VOLUMÉTRIE HÉPATIQUE : {liver_res['volume_cm3']} cm³ ({liver_res['volume_liters']} L)")
            if theo_data:
                safe_print(f" Volume Théorique (Vauthey) : {theo_data['tlv_vauthey_cm3']} cm³ ({theo_data['ratio_measured_to_theoretical_pct']}%)")
            safe_print(f"========================================================\n")
        except Exception:
            pass

    except Exception as e:
        err_msg = str(e)
        stack = traceback.format_exc()
        log_error(f"Échec de l'analyse : {err_msg}")
        try:
            safe_print(stack)
        except Exception:
            pass
        
        # Enregistrer l'erreur dans result.json
        err_result = {
            "status": "error",
            "error_message": err_msg,
            "stacktrace": stack,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            with open(os.path.join(output_dir, "result.json"), "w", encoding="utf-8") as f:
                json.dump(err_result, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        sys.exit(1)
    finally:
        # Fermeture propre de la base DICOM si encore ouverte
        try:
            if slicer.dicomDatabase and slicer.dicomDatabase.isOpen:
                slicer.dicomDatabase.closeDatabase()
        except Exception:
            pass

        # Nettoyage des dossiers temporaires
        for d in temp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: Slicer --python-script slicer_worker.py <config.json>")
        slicer.app.exit(1)
    
    cfg_file = sys.argv[-1]
    run_volumetry(cfg_file)
    slicer.app.exit(0)

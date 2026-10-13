/**
 * stl_viewer.js
 * Visualiseur 3D WebGL autonome pour fichiers STL médicaux (binaire et ASCII).
 * Fonctionne 100% hors-ligne, sans aucune dépendance externe (ni Three.js externe).
 */

class MedicalSTLViewer {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;

        this.gl = this.canvas.getContext('webgl', { antialias: true, alpha: true }) ||
                  this.canvas.getContext('experimental-webgl');

        if (!this.gl) {
            console.error("WebGL non supporté sur ce navigateur.");
            return;
        }

        this.options = Object.assign({
            defaultColor: [0.86, 0.28, 0.22, 1.0], // Rouge hépatique réaliste
            backgroundColor: [0.07, 0.09, 0.13, 1.0], // Fond sombre médical
            autoRotate: true,
            autoRotateSpeed: 0.008,
            wireframe: false,
        }, options);

        this.modelColor = [...this.options.defaultColor];
        this.autoRotate = this.options.autoRotate;
        this.wireframe = this.options.wireframe;

        // Matrices et état de caméra
        this.camera = {
            distance: 300,
            target: [0, 0, 0],
            rotationX: -0.4,
            rotationY: 0.6,
            panX: 0,
            panY: 0,
            minDistance: 50,
            maxDistance: 1200
        };

        this.isDragging = false;
        this.isPanning = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        this.trianglesCount = 0;
        this.vertexCount = 0;
        this.vertexBuffer = null;
        this.normalBuffer = null;
        this.meshes = [];

        // Prise en charge des plans de coupe orthogonaux MPR (Axial, Coronal, Sagittal)
        this.showMPRPlanes = false;
        this.mprPlanePcts = { axial: 0.5, coronal: 0.5, sagittal: 0.5 };
        this.mprPlanesData = null;
        this.bounds = null;

        this.initShaders();
        this.initEvents();
        this.resize();
        this.render();
    }

    initShaders() {
        const gl = this.gl;

        const vsSource = `
            attribute vec3 aPosition;
            attribute vec3 aNormal;

            uniform mat4 uProjectionMatrix;
            uniform mat4 uModelViewMatrix;
            uniform mat3 uNormalMatrix;

            varying vec3 vNormal;
            varying vec3 vPosition;

            void main() {
                vec4 viewPos = uModelViewMatrix * vec4(aPosition, 1.0);
                vPosition = viewPos.xyz;
                vNormal = normalize(uNormalMatrix * aNormal);
                gl_Position = uProjectionMatrix * viewPos;
            }
        `;

        const fsSource = `
            precision mediump float;

            varying vec3 vNormal;
            varying vec3 vPosition;

            uniform vec4 uColor;
            uniform vec3 uLightDirection1;
            uniform vec3 uLightDirection2;

            void main() {
                vec3 normal = normalize(vNormal);
                vec3 viewDir = normalize(-vPosition);

                // Éclairage directionnel 1 (Lumière clé)
                vec3 lightDir1 = normalize(uLightDirection1);
                float diff1 = max(dot(normal, lightDir1), 0.0);
                vec3 reflectDir1 = reflect(-lightDir1, normal);
                float spec1 = pow(max(dot(viewDir, reflectDir1), 0.0), 32.0);

                // Éclairage directionnel 2 (Lumière de débouchage douce)
                vec3 lightDir2 = normalize(uLightDirection2);
                float diff2 = max(dot(normal, lightDir2), 0.0) * 0.4;

                // Ambiance
                float ambient = 0.28;

                vec3 diffuse = uColor.rgb * (ambient + diff1 * 0.65 + diff2);
                vec3 specular = vec3(0.9, 0.95, 1.0) * (spec1 * 0.45);

                gl_FragColor = vec4(diffuse + specular, uColor.a);
            }
        `;

        const vs = this.compileShader(gl.VERTEX_SHADER, vsSource);
        const fs = this.compileShader(gl.FRAGMENT_SHADER, fsSource);

        const program = gl.createProgram();
        gl.attachShader(program, vs);
        gl.attachShader(program, fs);
        gl.linkProgram(program);

        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
            console.error("Erreur de liaison shader WebGL:", gl.getProgramInfoLog(program));
            return;
        }

        this.program = program;
        gl.useProgram(program);

        this.attribs = {
            position: gl.getAttribLocation(program, "aPosition"),
            normal: gl.getAttribLocation(program, "aNormal"),
        };

        this.uniforms = {
            projectionMatrix: gl.getUniformLocation(program, "uProjectionMatrix"),
            modelViewMatrix: gl.getUniformLocation(program, "uModelViewMatrix"),
            normalMatrix: gl.getUniformLocation(program, "uNormalMatrix"),
            color: gl.getUniformLocation(program, "uColor"),
            lightDirection1: gl.getUniformLocation(program, "uLightDirection1"),
            lightDirection2: gl.getUniformLocation(program, "uLightDirection2"),
        };

        gl.enable(gl.DEPTH_TEST);
        gl.enable(gl.CULL_FACE);
        gl.cullFace(gl.BACK);
    }

    compileShader(type, source) {
        const gl = this.gl;
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            console.error("Erreur compilation shader:", gl.getShaderInfoLog(shader));
            gl.deleteShader(shader);
            return null;
        }
        return shader;
    }

    initEvents() {
        const canvas = this.canvas;

        canvas.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.isPanning = e.button === 2 || e.shiftKey;
            this.lastMouseX = e.clientX;
            this.lastMouseY = e.clientY;
            this.autoRotate = false; // Arrêt rotation auto au clic
        });

        window.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return;

            const dx = e.clientX - this.lastMouseX;
            const dy = e.clientY - this.lastMouseY;

            if (this.isPanning) {
                const panSpeed = this.camera.distance * 0.0015;
                this.camera.panX += dx * panSpeed;
                this.camera.panY -= dy * panSpeed;
            } else {
                this.camera.rotationY += dx * 0.008;
                this.camera.rotationX += dy * 0.008;
                // Limiter le tangage
                this.camera.rotationX = Math.max(-Math.PI / 2 + 0.05, Math.min(Math.PI / 2 - 0.05, this.camera.rotationX));
            }

            this.lastMouseX = e.clientX;
            this.lastMouseY = e.clientY;
        });

        window.addEventListener('mouseup', () => {
            this.isDragging = false;
        });

        canvas.addEventListener('contextmenu', (e) => e.preventDefault());

        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomSpeed = this.camera.distance * 0.001;
            this.camera.distance += e.deltaY * zoomSpeed;
            this.camera.distance = Math.max(this.camera.minDistance, Math.min(this.camera.maxDistance, this.camera.distance));
            this.autoRotate = false;
        }, { passive: false });

        // Support tactile mobile / trackpad pinch
        let touchStartDist = 0;
        canvas.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                this.isDragging = true;
                this.isPanning = false;
                this.lastMouseX = e.touches[0].clientX;
                this.lastMouseY = e.touches[0].clientY;
                this.autoRotate = false;
            } else if (e.touches.length === 2) {
                touchStartDist = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
            }
        });

        canvas.addEventListener('touchmove', (e) => {
            if (e.touches.length === 1 && this.isDragging) {
                const dx = e.touches[0].clientX - this.lastMouseX;
                const dy = e.touches[0].clientY - this.lastMouseY;
                this.camera.rotationY += dx * 0.008;
                this.camera.rotationX += dy * 0.008;
                this.lastMouseX = e.touches[0].clientX;
                this.lastMouseY = e.touches[0].clientY;
            } else if (e.touches.length === 2) {
                const dist = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                const diff = touchStartDist - dist;
                this.camera.distance += diff * 0.8;
                this.camera.distance = Math.max(this.camera.minDistance, Math.min(this.camera.maxDistance, this.camera.distance));
                touchStartDist = dist;
            }
        });

        canvas.addEventListener('touchend', () => {
            this.isDragging = false;
        });

        window.addEventListener('resize', () => this.resize());
    }

    resize() {
        const width = this.canvas.parentElement ? this.canvas.parentElement.clientWidth : 600;
        const height = this.canvas.parentElement ? this.canvas.parentElement.clientHeight : 450;
        
        if (this.canvas.width !== width || this.canvas.height !== height) {
            this.canvas.width = width;
            this.canvas.height = height;
            this.gl.viewport(0, 0, width, height);
        }
    }

    loadSTLFromUrl(url) {
        this.clearMeshes();
        return fetch(url)
            .then(res => {
                if (!res.ok) throw new Error("Fichier STL introuvable: " + res.statusText);
                return res.arrayBuffer();
            })
            .then(buffer => {
                this.parseSTL(buffer);
                return true;
            })
            .catch(err => {
                console.error("Erreur chargement STL:", err);
                throw err;
            });
    }

    clearMeshes() {
        const gl = this.gl;
        if (this.meshes && this.meshes.length > 0) {
            for (const mesh of this.meshes) {
                if (mesh.vertexBuffer) gl.deleteBuffer(mesh.vertexBuffer);
                if (mesh.normalBuffer) gl.deleteBuffer(mesh.normalBuffer);
            }
            this.meshes = [];
        }
    }

    async loadSegments(segmentsList, onProgress = null) {
        this.clearMeshes();
        const gl = this.gl;

        // Téléchargement parallèle de tous les fichiers STL
        let loadedCount = 0;
        const total = segmentsList.length;

        const downloadPromises = segmentsList.map(seg => {
            return fetch(seg.url)
                .then(res => {
                    if (!res.ok) throw new Error(`Segment ${seg.id} introuvable (${res.statusText})`);
                    return res.arrayBuffer();
                })
                .then(buffer => {
                    loadedCount++;
                    if (typeof onProgress === 'function') onProgress(loadedCount, total);
                    const parsed = this.parseSTLData(buffer);
                    return { seg, parsed };
                });
        });

        const results = await Promise.all(downloadPromises);

        // 1. Calcul du cube englobant global (Bounding Box partagé) pour respecter les coordonnées spatiales relatives
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

        for (const item of results) {
            const v = item.parsed.vertices;
            for (let i = 0; i < v.length; i += 3) {
                const x = v[i], y = v[i + 1], z = v[i + 2];
                if (x < minX) minX = x; if (x > maxX) maxX = x;
                if (y < minY) minY = y; if (y > maxY) maxY = y;
                if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
            }
        }

        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;
        const centerZ = (minZ + maxZ) / 2;

        const sizeX = maxX - minX;
        const sizeY = maxY - minY;
        const sizeZ = maxZ - minZ;
        const maxDim = Math.max(sizeX, sizeY, sizeZ);
        const scale = maxDim > 0 ? 150.0 / maxDim : 1.0;

        this.bounds = {
            minX, maxX, minY, maxY, minZ, maxZ,
            centerX, centerY, centerZ,
            maxDim, scale,
            bMinX: (minX - centerX) * scale,
            bMaxX: (maxX - centerX) * scale,
            bMinY: (minY - centerY) * scale,
            bMaxY: (maxY - centerY) * scale,
            bMinZ: (minZ - centerZ) * scale,
            bMaxZ: (maxZ - centerZ) * scale
        };
        if (this.showMPRPlanes) {
            this.updateMPRPlanesBuffers();
        }

        let totalTriangles = 0;
        let totalVertices = 0;

        // 2. Normalisation et création des buffers WebGL pour chaque segment
        for (const item of results) {
            const v = item.parsed.vertices;
            for (let i = 0; i < v.length; i += 3) {
                v[i] = (v[i] - centerX) * scale;
                v[i + 1] = (v[i + 1] - centerY) * scale;
                v[i + 2] = (v[i + 2] - centerZ) * scale;
            }

            const vBuffer = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, vBuffer);
            gl.bufferData(gl.ARRAY_BUFFER, v, gl.STATIC_DRAW);

            const nBuffer = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, nBuffer);
            gl.bufferData(gl.ARRAY_BUFFER, item.parsed.normals, gl.STATIC_DRAW);

            // Résolution de la couleur
            let meshColor = [0.2, 0.7, 0.9, 1.0];
            if (item.seg.color_rgb && Array.isArray(item.seg.color_rgb)) {
                meshColor = [
                    item.seg.color_rgb[0] / 255.0,
                    item.seg.color_rgb[1] / 255.0,
                    item.seg.color_rgb[2] / 255.0,
                    1.0
                ];
            } else if (item.seg.color_hex) {
                meshColor = this.hexToRgba(item.seg.color_hex);
            }

            const meshObj = {
                id: item.seg.id,
                number: item.seg.number || '',
                name: item.seg.name || item.seg.id,
                subname: item.seg.subname || '',
                lobe: item.seg.lobe || '',
                volume_cm3: item.seg.volume_cm3 || 0,
                pct_of_liver: item.seg.pct_of_liver || 0,
                color: meshColor,
                defaultColor: [...meshColor],
                colorHex: item.seg.color_hex || '#38bdf8',
                visible: item.seg.visible !== undefined ? item.seg.visible : true,
                is_vessel: !!item.seg.is_vessel,
                vertexCount: item.parsed.vertexCount,
                trianglesCount: item.parsed.numTriangles,
                vertexBuffer: vBuffer,
                normalBuffer: nBuffer
            };

            this.meshes.push(meshObj);
            totalTriangles += item.parsed.numTriangles;
            totalVertices += item.parsed.vertexCount;
        }

        this.trianglesCount = totalTriangles;
        this.vertexCount = totalVertices;
        this.camera.distance = 250;
        this.camera.panX = 0;
        this.camera.panY = 0;

        console.log(`Segmentation multi-pièces chargée : ${this.meshes.length} segments, ${this.trianglesCount} triangles.`);
        return this.meshes;
    }

    parseSTLData(buffer) {
        const dataView = new DataView(buffer);
        const isBinary = buffer.byteLength > 84 && dataView.getUint32(80, true) * 50 + 84 === buffer.byteLength;

        let vertices, normals, numTriangles, vertexCount;

        if (isBinary) {
            numTriangles = dataView.getUint32(80, true);
            vertexCount = numTriangles * 3;
            vertices = new Float32Array(vertexCount * 3);
            normals = new Float32Array(vertexCount * 3);

            let offset = 84;
            let vIdx = 0;

            for (let i = 0; i < numTriangles; i++) {
                const nx = dataView.getFloat32(offset, true);
                const ny = dataView.getFloat32(offset + 4, true);
                const nz = dataView.getFloat32(offset + 8, true);
                offset += 12;

                for (let j = 0; j < 3; j++) {
                    vertices[vIdx] = dataView.getFloat32(offset, true);
                    vertices[vIdx + 1] = dataView.getFloat32(offset + 4, true);
                    vertices[vIdx + 2] = dataView.getFloat32(offset + 8, true);
                    offset += 12;

                    normals[vIdx] = nx;
                    normals[vIdx + 1] = ny;
                    normals[vIdx + 2] = nz;
                    vIdx += 3;
                }
                offset += 2; // Attribut STL binaire
            }
        } else {
            // STL ASCII fallback
            const text = new TextDecoder().decode(buffer);
            const lines = text.split('\n');
            const vertList = [];
            const normList = [];
            let currentNormal = [0, 0, 1];

            for (let line of lines) {
                line = line.trim();
                if (line.startsWith('facet normal')) {
                    const parts = line.split(/\s+/);
                    currentNormal = [parseFloat(parts[2]), parseFloat(parts[3]), parseFloat(parts[4])];
                } else if (line.startsWith('vertex')) {
                    const parts = line.split(/\s+/);
                    vertList.push(parseFloat(parts[1]), parseFloat(parts[2]), parseFloat(parts[3]));
                    normList.push(currentNormal[0], currentNormal[1], currentNormal[2]);
                }
            }

            vertexCount = vertList.length / 3;
            numTriangles = vertexCount / 3;
            vertices = new Float32Array(vertList);
            normals = new Float32Array(normList);
        }

        return { vertices, normals, numTriangles, vertexCount };
    }

    parseSTL(buffer) {
        const gl = this.gl;
        const parsed = this.parseSTLData(buffer);

        this.trianglesCount = parsed.numTriangles;
        this.vertexCount = parsed.vertexCount;

        const vertices = parsed.vertices;
        const normals = parsed.normals;

        // Recentrage et mise à l'échelle du maillage unique
        this.centerAndScaleMesh(vertices, normals);

        // Upload des buffers WebGL
        if (!this.vertexBuffer) this.vertexBuffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

        if (!this.normalBuffer) this.normalBuffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.normalBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);

        console.log(`Modèle 3D unique chargé : ${this.trianglesCount} polygones.`);
    }

    centerAndScaleMesh(vertices, normals) {
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

        for (let i = 0; i < vertices.length; i += 3) {
            const x = vertices[i];
            const y = vertices[i + 1];
            const z = vertices[i + 2];

            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
            if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
        }

        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;
        const centerZ = (minZ + maxZ) / 2;

        const sizeX = maxX - minX;
        const sizeY = maxY - minY;
        const sizeZ = maxZ - minZ;
        const maxDim = Math.max(sizeX, sizeY, sizeZ);

        const scale = maxDim > 0 ? 150.0 / maxDim : 1.0;

        for (let i = 0; i < vertices.length; i += 3) {
            vertices[i] = (vertices[i] - centerX) * scale;
            vertices[i + 1] = (vertices[i + 1] - centerY) * scale;
            vertices[i + 2] = (vertices[i + 2] - centerZ) * scale;
        }

        this.bounds = {
            minX, maxX, minY, maxY, minZ, maxZ,
            centerX, centerY, centerZ,
            maxDim, scale,
            bMinX: (minX - centerX) * scale,
            bMaxX: (maxX - centerX) * scale,
            bMinY: (minY - centerY) * scale,
            bMaxY: (maxY - centerY) * scale,
            bMinZ: (minZ - centerZ) * scale,
            bMaxZ: (maxZ - centerZ) * scale
        };
        if (this.showMPRPlanes) {
            this.updateMPRPlanesBuffers();
        }

        this.camera.distance = 250;
        this.camera.panX = 0;
        this.camera.panY = 0;
    }

    hexToRgba(hex, alpha = 1.0) {
        if (!hex) return [0.2, 0.7, 0.9, alpha];
        let c = hex.replace('#', '');
        if (c.length === 3) c = c.split('').map(x => x + x).join('');
        const num = parseInt(c, 16);
        return [
            ((num >> 16) & 255) / 255.0,
            ((num >> 8) & 255) / 255.0,
            (num & 255) / 255.0,
            alpha
        ];
    }

    setMeshVisibility(id, visible) {
        const mesh = this.meshes.find(m => m.id === id);
        if (mesh) {
            mesh.visible = !!visible;
            return mesh.visible;
        }
        return false;
    }

    isMeshVisible(id) {
        const mesh = this.meshes.find(m => m.id === id);
        return mesh ? mesh.visible : false;
    }

    getMeshVisibilityMap() {
        const map = {};
        this.meshes.forEach(m => {
            map[m.id] = m.visible;
        });
        return map;
    }

    setOnlyMeshesVisible(ids) {
        const idSet = new Set(ids);
        this.meshes.forEach(m => {
            m.visible = idSet.has(m.id);
        });
    }

    toggleMeshVisibility(id) {
        const mesh = this.meshes.find(m => m.id === id);
        if (mesh) {
            mesh.visible = !mesh.visible;
            return mesh.visible;
        }
        return false;
    }

    showAllMeshes() {
        this.meshes.forEach(m => m.visible = true);
    }

    hideAllMeshes() {
        this.meshes.forEach(m => m.visible = false);
    }

    resetMeshColors() {
        this.meshes.forEach(m => {
            m.color = [...m.defaultColor];
        });
    }

    setParenchymaOpacity(alpha = 0.35) {
        this.parenchymaOpacity = Math.max(0.0, Math.min(1.0, alpha));
        this.isTranslucent = (this.parenchymaOpacity < 0.95 && this.parenchymaOpacity > 0.01);
        if (this.meshes && this.meshes.length > 0) {
            this.meshes.forEach(m => {
                if (!m.is_vessel) {
                    m.color[3] = this.parenchymaOpacity;
                    m.visible = (this.parenchymaOpacity > 0.005);
                } else {
                    m.color[3] = 1.0; // Vaisseaux restent opaques et visibles à l'intérieur
                    m.visible = true;
                }
            });
        }
        return this.isTranslucent;
    }

    toggleParenchymaOpacity() {
        if (this.isTranslucent) {
            return this.setParenchymaOpacity(1.0);
        } else {
            return this.setParenchymaOpacity(0.32);
        }
    }

    setIsolatedVascularView(active = true) {
        this.isolatedVascularMode = !!active;
        if (this.meshes && this.meshes.length > 0) {
            this.meshes.forEach(m => {
                if (!m.is_vessel) {
                    m.visible = !this.isolatedVascularMode;
                    if (!this.isolatedVascularMode) {
                        m.color[3] = this.parenchymaOpacity || 0.32;
                    }
                } else {
                    m.visible = true;
                    m.color[3] = 1.0;
                }
            });
        }
        return this.isolatedVascularMode;
    }

    toggleIsolatedVascularView() {
        return this.setIsolatedVascularView(!this.isolatedVascularMode);
    }

    setColor(r, g, b, a = 1.0) {
        this.modelColor = [r, g, b, a];
        if (this.meshes && this.meshes.length > 0) {
            this.meshes.forEach(m => {
                m.color = [r, g, b, a];
            });
        }
    }

    setPresetColor(preset) {
        if (preset === 'anatomical') {
            this.resetMeshColors();
            return;
        }

        switch (preset) {
            case 'liver': // Rouge/bordeaux hépatique
                this.setColor(0.86, 0.28, 0.22, 1.0);
                break;
            case 'amber': // Ambre / doré
                this.setColor(0.92, 0.62, 0.18, 1.0);
                break;
            case 'cyan': // Bleu / Cyan médical
                this.setColor(0.12, 0.72, 0.88, 1.0);
                break;
            case 'emerald': // Vert émeraude
                this.setColor(0.16, 0.78, 0.48, 1.0);
                break;
            case 'bone': // Osseux / Blanc
                this.setColor(0.88, 0.88, 0.92, 1.0);
                break;
            default:
                this.setColor(0.86, 0.28, 0.22, 1.0);
        }
    }

    toggleAutoRotate() {
        this.autoRotate = !this.autoRotate;
        return this.autoRotate;
    }

    toggleWireframe() {
        this.wireframe = !this.wireframe;
        return this.wireframe;
    }

    resetView() {
        this.camera.rotationX = -0.4;
        this.camera.rotationY = 0.6;
        this.camera.distance = 250;
        this.camera.panX = 0;
        this.camera.panY = 0;
        this.autoRotate = true;
    }

    setAnatomicalView(viewName) {
        this.autoRotate = false;
        this.camera.panX = 0;
        this.camera.panY = 0;
        this.camera.distance = 260;

        switch (viewName) {
            case 'superior': // Axiale Crâniale (Vue par le haut)
                this.camera.rotationX = -Math.PI / 2 + 0.05;
                this.camera.rotationY = 0;
                break;
            case 'inferior': // Axiale Caudale (Vue par le bas / Hile)
                this.camera.rotationX = Math.PI / 2 - 0.05;
                this.camera.rotationY = 0;
                break;
            case 'anterior': // Vue Antérieure (Face)
                this.camera.rotationX = 0;
                this.camera.rotationY = 0;
                break;
            case 'posterior': // Vue Postérieure (Dos)
                this.camera.rotationX = 0;
                this.camera.rotationY = Math.PI;
                break;
            case 'right': // Profil droit
                this.camera.rotationX = 0;
                this.camera.rotationY = -Math.PI / 2;
                break;
            case 'left': // Profil gauche
                this.camera.rotationX = 0;
                this.camera.rotationY = Math.PI / 2;
                break;
            case 'isometric':
            case 'iso':
                this.camera.rotationX = -0.42;
                this.camera.rotationY = 0.58;
                break;
            case 'default':
            default:
                this.resetView();
                break;
        }
    }

    rotateBy(deltaX, deltaY) {
        this.autoRotate = false;
        this.camera.rotationX += deltaX;
        this.camera.rotationY += deltaY;
        this.camera.rotationX = Math.max(-Math.PI / 2 + 0.05, Math.min(Math.PI / 2 - 0.05, this.camera.rotationX));
    }

    captureScreenshot() {
        return this.canvas.toDataURL("image/png");
    }

    setMPRPlanes(axialPct = 0.5, coronalPct = 0.5, sagittalPct = 0.5, visible = true) {
        this.showMPRPlanes = !!visible;
        this.mprPlanePcts = {
            axial: Math.max(0.0, Math.min(1.0, axialPct)),
            coronal: Math.max(0.0, Math.min(1.0, coronalPct)),
            sagittal: Math.max(0.0, Math.min(1.0, sagittalPct))
        };
        this.updateMPRPlanesBuffers();
    }

    updateMPRPlanesBuffers() {
        const gl = this.gl;
        if (!gl) return;

        const b = this.bounds || {
            bMinX: -75, bMaxX: 75,
            bMinY: -75, bMaxY: 75,
            bMinZ: -75, bMaxZ: 75
        };

        const pad = 1.08;
        const x0 = b.bMinX * pad, x1 = b.bMaxX * pad;
        const y0 = b.bMinY * pad, y1 = b.bMaxY * pad;
        const z0 = b.bMinZ * pad, z1 = b.bMaxZ * pad;

        const zCur = z0 + this.mprPlanePcts.axial * (z1 - z0);
        const yCur = y0 + this.mprPlanePcts.coronal * (y1 - y0);
        const xCur = x0 + this.mprPlanePcts.sagittal * (x1 - x0);

        if (!this.mprPlanesData) {
            this.mprPlanesData = [
                {
                    id: 'axial',
                    colorQuad: [0.22, 0.74, 0.97, 0.30], // Cyan
                    colorBorder: [0.22, 0.74, 0.97, 1.0],
                    quadBuffer: gl.createBuffer(),
                    quadNormalBuffer: gl.createBuffer(),
                    borderBuffer: gl.createBuffer(),
                    visible: true
                },
                {
                    id: 'coronal',
                    colorQuad: [0.20, 0.83, 0.60, 0.30], // Vert émeraude
                    colorBorder: [0.20, 0.83, 0.60, 1.0],
                    quadBuffer: gl.createBuffer(),
                    quadNormalBuffer: gl.createBuffer(),
                    borderBuffer: gl.createBuffer(),
                    visible: true
                },
                {
                    id: 'sagittal',
                    colorQuad: [0.96, 0.62, 0.04, 0.30], // Ambre / Orange
                    colorBorder: [0.96, 0.62, 0.04, 1.0],
                    quadBuffer: gl.createBuffer(),
                    quadNormalBuffer: gl.createBuffer(),
                    borderBuffer: gl.createBuffer(),
                    visible: true
                }
            ];
        }

        // 1. Plan Axial (Z)
        const axVerts = new Float32Array([
            x0, y0, zCur,   x1, y0, zCur,   x1, y1, zCur,
            x0, y0, zCur,   x1, y1, zCur,   x0, y1, zCur
        ]);
        const axNorms = new Float32Array([
            0, 0, 1,   0, 0, 1,   0, 0, 1,
            0, 0, 1,   0, 0, 1,   0, 0, 1
        ]);
        const axBorders = new Float32Array([
            x0, y0, zCur,   x1, y0, zCur,
            x1, y0, zCur,   x1, y1, zCur,
            x1, y1, zCur,   x0, y1, zCur,
            x0, y1, zCur,   x0, y0, zCur
        ]);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[0].quadBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, axVerts, gl.DYNAMIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[0].quadNormalBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, axNorms, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[0].borderBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, axBorders, gl.DYNAMIC_DRAW);

        // 2. Plan Coronal (Y)
        const corVerts = new Float32Array([
            x0, yCur, z0,   x1, yCur, z0,   x1, yCur, z1,
            x0, yCur, z0,   x1, yCur, z1,   x0, yCur, z1
        ]);
        const corNorms = new Float32Array([
            0, 1, 0,   0, 1, 0,   0, 1, 0,
            0, 1, 0,   0, 1, 0,   0, 1, 0
        ]);
        const corBorders = new Float32Array([
            x0, yCur, z0,   x1, yCur, z0,
            x1, yCur, z0,   x1, yCur, z1,
            x1, yCur, z1,   x0, yCur, z1,
            x0, yCur, z1,   x0, yCur, z0
        ]);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[1].quadBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, corVerts, gl.DYNAMIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[1].quadNormalBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, corNorms, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[1].borderBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, corBorders, gl.DYNAMIC_DRAW);

        // 3. Plan Sagittal (X)
        const sagVerts = new Float32Array([
            xCur, y0, z0,   xCur, y1, z0,   xCur, y1, z1,
            xCur, y0, z0,   xCur, y1, z1,   xCur, y0, z1
        ]);
        const sagNorms = new Float32Array([
            1, 0, 0,   1, 0, 0,   1, 0, 0,
            1, 0, 0,   1, 0, 0,   1, 0, 0
        ]);
        const sagBorders = new Float32Array([
            xCur, y0, z0,   xCur, y1, z0,
            xCur, y1, z0,   xCur, y1, z1,
            xCur, y1, z1,   xCur, y0, z1,
            xCur, y0, z1,   xCur, y0, z0
        ]);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[2].quadBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, sagVerts, gl.DYNAMIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[2].quadNormalBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, sagNorms, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.mprPlanesData[2].borderBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, sagBorders, gl.DYNAMIC_DRAW);
    }

    render() {
        requestAnimationFrame(() => this.render());

        const gl = this.gl;
        if (!gl || !this.program) return;

        this.resize();

        if (this.autoRotate && !this.isDragging) {
            this.camera.rotationY += this.options.autoRotateSpeed;
        }

        // Nettoyage fond
        const bg = this.options.backgroundColor;
        gl.clearColor(bg[0], bg[1], bg[2], bg[3]);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

        gl.useProgram(this.program);

        // Matrice de projection
        const aspect = this.canvas.width / this.canvas.height;
        const projMatrix = this.createPerspectiveMatrix(45 * Math.PI / 180, aspect, 1.0, 3000.0);

        // Matrice vue/modèle
        const mvMatrix = this.createIdentityMatrix();
        this.translateMatrix(mvMatrix, this.camera.panX, this.camera.panY, -this.camera.distance);
        this.rotateMatrix(mvMatrix, this.camera.rotationX, 1, 0, 0);
        this.rotateMatrix(mvMatrix, this.camera.rotationY, 0, 1, 0);

        // Matrice des normales (3x3)
        const normMatrix = this.createNormalMatrix(mvMatrix);

        gl.uniformMatrix4fv(this.uniforms.projectionMatrix, false, projMatrix);
        gl.uniformMatrix4fv(this.uniforms.modelViewMatrix, false, mvMatrix);
        gl.uniformMatrix3fv(this.uniforms.normalMatrix, false, normMatrix);

        gl.uniform3f(this.uniforms.lightDirection1, 0.5, 0.8, 1.0);
        gl.uniform3f(this.uniforms.lightDirection2, -0.6, -0.3, 0.5);

        // 1. Rendu Multi-Segments et Vaisseaux 3D (si plusieurs segments/vaisseaux chargés)
        if (this.meshes && this.meshes.length > 0) {
            const hasAlpha = this.meshes.some(m => m.visible && m.color && m.color[3] < 0.98);

            if (hasAlpha) {
                gl.enable(gl.BLEND);
                gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
            } else {
                gl.disable(gl.BLEND);
            }

            // Passe A : Maillages opaques (Vaisseaux sanguins, ou segments opaques)
            gl.depthMask(true);
            for (let i = 0; i < this.meshes.length; i++) {
                const mesh = this.meshes[i];
                if (!mesh.visible || !mesh.vertexBuffer || !mesh.vertexCount) continue;
                if (hasAlpha && mesh.color && mesh.color[3] < 0.98) continue; // Les translucides seront rendus en passe B

                gl.uniform4fv(this.uniforms.color, mesh.color);

                gl.bindBuffer(gl.ARRAY_BUFFER, mesh.vertexBuffer);
                gl.enableVertexAttribArray(this.attribs.position);
                gl.vertexAttribPointer(this.attribs.position, 3, gl.FLOAT, false, 0, 0);

                gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normalBuffer);
                gl.enableVertexAttribArray(this.attribs.normal);
                gl.vertexAttribPointer(this.attribs.normal, 3, gl.FLOAT, false, 0, 0);

                if (this.wireframe) {
                    gl.drawArrays(gl.LINES, 0, mesh.vertexCount);
                } else {
                    gl.drawArrays(gl.TRIANGLES, 0, mesh.vertexCount);
                }
            }

            // Passe B : Maillages translucides (Parenchyme hépatique, segments de Couinaud)
            if (hasAlpha) {
                gl.depthMask(false);
                // Rendu des surfaces translucides avec test de profondeur
                for (let i = 0; i < this.meshes.length; i++) {
                    const mesh = this.meshes[i];
                    if (!mesh.visible || !mesh.vertexBuffer || !mesh.vertexCount) continue;
                    if (!mesh.color || mesh.color[3] >= 0.98) continue; // Déjà rendu en passe A

                    gl.uniform4fv(this.uniforms.color, mesh.color);

                    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.vertexBuffer);
                    gl.enableVertexAttribArray(this.attribs.position);
                    gl.vertexAttribPointer(this.attribs.position, 3, gl.FLOAT, false, 0, 0);

                    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normalBuffer);
                    gl.enableVertexAttribArray(this.attribs.normal);
                    gl.vertexAttribPointer(this.attribs.normal, 3, gl.FLOAT, false, 0, 0);

                    if (this.wireframe) {
                        gl.drawArrays(gl.LINES, 0, mesh.vertexCount);
                    } else {
                        gl.drawArrays(gl.TRIANGLES, 0, mesh.vertexCount);
                    }
                }
                gl.depthMask(true);
            }
        } 
        // 2. Rendu Modèle Unique consolidé (mode secours / mono-organe)
        else if (this.vertexCount && this.vertexBuffer) {
            gl.uniform4fv(this.uniforms.color, this.modelColor);

            gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
            gl.enableVertexAttribArray(this.attribs.position);
            gl.vertexAttribPointer(this.attribs.position, 3, gl.FLOAT, false, 0, 0);

            gl.bindBuffer(gl.ARRAY_BUFFER, this.normalBuffer);
            gl.enableVertexAttribArray(this.attribs.normal);
            gl.vertexAttribPointer(this.attribs.normal, 3, gl.FLOAT, false, 0, 0);

            if (this.wireframe) {
                gl.drawArrays(gl.LINES, 0, this.vertexCount);
            } else {
                gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
            }
        }

        // 3. Rendu des 3 plans de coupe orthogonaux MPR (Axial, Coronal, Sagittal)
        if (this.showMPRPlanes && this.mprPlanesData) {
            gl.disable(gl.CULL_FACE);
            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
            gl.depthMask(false);

            for (let i = 0; i < this.mprPlanesData.length; i++) {
                const p = this.mprPlanesData[i];
                if (!p.visible) continue;

                // Quads semi-transparents du plan
                gl.uniform4fv(this.uniforms.color, p.colorQuad);
                gl.bindBuffer(gl.ARRAY_BUFFER, p.quadBuffer);
                gl.enableVertexAttribArray(this.attribs.position);
                gl.vertexAttribPointer(this.attribs.position, 3, gl.FLOAT, false, 0, 0);

                gl.bindBuffer(gl.ARRAY_BUFFER, p.quadNormalBuffer);
                gl.enableVertexAttribArray(this.attribs.normal);
                gl.vertexAttribPointer(this.attribs.normal, 3, gl.FLOAT, false, 0, 0);

                gl.drawArrays(gl.TRIANGLES, 0, 6);

                // Bordures vives du plan
                gl.uniform4fv(this.uniforms.color, p.colorBorder);
                gl.bindBuffer(gl.ARRAY_BUFFER, p.borderBuffer);
                gl.vertexAttribPointer(this.attribs.position, 3, gl.FLOAT, false, 0, 0);

                gl.drawArrays(gl.LINES, 0, 8);
            }

            gl.depthMask(true);
            gl.enable(gl.CULL_FACE);
        }
    }

    // --- Utilitaires de matrices mathématiques 4x4 et 3x3 ---

    createIdentityMatrix() {
        return new Float32Array([
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1
        ]);
    }

    createPerspectiveMatrix(fovy, aspect, near, far) {
        const f = 1.0 / Math.tan(fovy / 2);
        const nf = 1 / (near - far);
        return new Float32Array([
            f / aspect, 0, 0, 0,
            0, f, 0, 0,
            0, 0, (far + near) * nf, -1,
            0, 0, (2 * far * near) * nf, 0
        ]);
    }

    translateMatrix(out, x, y, z) {
        out[12] += out[0] * x + out[4] * y + out[8] * z;
        out[13] += out[1] * x + out[5] * y + out[9] * z;
        out[14] += out[2] * x + out[6] * y + out[10] * z;
        out[15] += out[3] * x + out[7] * y + out[11] * z;
    }

    rotateMatrix(out, rad, x, y, z) {
        const len = Math.hypot(x, y, z);
        if (len < 0.00001) return;
        x /= len; y /= len; z /= len;

        const s = Math.sin(rad);
        const c = Math.cos(rad);
        const t = 1 - c;

        const a00 = out[0], a01 = out[1], a02 = out[2], a03 = out[3];
        const a10 = out[4], a11 = out[5], a12 = out[6], a13 = out[7];
        const a20 = out[8], a21 = out[9], a22 = out[10], a23 = out[11];

        const b00 = x * x * t + c, b01 = y * x * t + z * s, b02 = z * x * t - y * s;
        const b10 = x * y * t - z * s, b11 = y * y * t + c, b12 = z * y * t + x * s;
        const b20 = x * z * t + y * s, b21 = y * z * t - x * s, b22 = z * z * t + c;

        out[0] = a00 * b00 + a10 * b01 + a20 * b02;
        out[1] = a01 * b00 + a11 * b01 + a21 * b02;
        out[2] = a02 * b00 + a12 * b01 + a22 * b02;
        out[3] = a03 * b00 + a13 * b01 + a23 * b02;

        out[4] = a00 * b10 + a10 * b11 + a20 * b12;
        out[5] = a01 * b10 + a11 * b11 + a21 * b12;
        out[6] = a02 * b10 + a12 * b11 + a22 * b12;
        out[7] = a03 * b10 + a13 * b11 + a23 * b12;

        out[8] = a00 * b20 + a10 * b21 + a20 * b22;
        out[9] = a01 * b20 + a11 * b21 + a21 * b22;
        out[10] = a02 * b20 + a12 * b21 + a22 * b22;
        out[11] = a03 * b20 + a13 * b21 + a23 * b22;
    }

    createNormalMatrix(m) {
        // Extraction sous-matrice 3x3 et inversion-transposition simplifiée pour rotation pure
        return new Float32Array([
            m[0], m[1], m[2],
            m[4], m[5], m[6],
            m[8], m[9], m[10]
        ]);
    }
}

// Export global pour utilisation dans app.js
window.MedicalSTLViewer = MedicalSTLViewer;

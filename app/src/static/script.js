document.addEventListener('DOMContentLoaded', () => {
    const imageInput = document.getElementById('imageInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const videoPreviewContainer = document.getElementById('videoPreviewContainer');
    const videoPreview = document.getElementById('videoPreview');
    const missionNameInput = document.getElementById('missionNameInput');
    const vlmModelSelect = document.getElementById('vlmModelSelect');
    const detectorConfInput = document.getElementById('detectorConfInput');
    const detectorIouInput = document.getElementById('detectorIouInput');
    const detectorWbfIouInput = document.getElementById('detectorWbfIouInput');
    const detectorWbfSkipInput = document.getElementById('detectorWbfSkipInput');
    const detectorFinalThresholdInput = document.getElementById('detectorFinalThresholdInput');
    const detectorMinSupportInput = document.getElementById('detectorMinSupportInput');
    const videoOverlapInput = document.getElementById('videoOverlapInput');
    const videoDedupInput = document.getElementById('videoDedupInput');
    const videoMaxFramesInput = document.getElementById('videoMaxFramesInput');
    const persistDbToggle = document.getElementById('persistDbToggle');
    const fileLabel = document.querySelector('.file-label');
    const emptyState = document.getElementById('emptyState');

    const loadingIndicator = document.getElementById('loadingIndicator');
    const errorContainer = document.getElementById('errorContainer');
    const resultSection = document.getElementById('resultSection');
    const reportSummary = document.getElementById('reportSummary');
    const finalTime = document.getElementById('finalTime');
    const resultMetaLine = document.getElementById('resultMetaLine');
    const resultViewerTitle = document.getElementById('resultViewerTitle');
    const detectorDebugPanel = document.getElementById('detectorDebugPanel');
    const videoFramesStrip = document.getElementById('videoFramesStrip');
    const markdownContainer = document.getElementById('markdownReportContainer');
    const actionsList = document.getElementById('recommendedActionsList');
    const boxesTableBody = document.querySelector('#boxesTable tbody');
    const canvas = document.getElementById('resultCanvas');
    const resultImage = document.getElementById('resultImage');

    const connectionMode = document.getElementById('connectionMode');
    const bridgeEndpoint = document.getElementById('bridgeEndpoint');
    const publicTunnel = document.getElementById('publicTunnel');
    const modelEndpoint = document.getElementById('modelEndpoint');
    const modelStatus = document.getElementById('modelStatus');
    const modelApiKeyStatus = document.getElementById('modelApiKeyStatus');
    const tunnelStatus = document.getElementById('tunnelStatus');
    const tunnelError = document.getElementById('tunnelError');
    const modelError = document.getElementById('modelError');
    const supabaseStatus = document.getElementById('supabaseStatus');
    const refreshRuntimeBtn = document.getElementById('refreshRuntimeBtn');
    const openPublicTunnelLink = document.getElementById('openPublicTunnelLink');
    const openModelLink = document.getElementById('openModelLink');
    const dashboardSeverityFilter = document.getElementById('dashboardSeverityFilter');
    const dashboardTimeFilter = document.getElementById('dashboardTimeFilter');
    const dashboardConfidenceFilter = document.getElementById('dashboardConfidenceFilter');
    const recenterMapBtn = document.getElementById('recenterMapBtn');
    const resetDashboardFilters = document.getElementById('resetDashboardFilters');
    const evidenceDrawer = document.getElementById('evidenceDrawer');
    const toggleEvidenceDrawerBtn = document.getElementById('toggleEvidenceDrawerBtn');
    const evidenceEmpty = document.getElementById('evidenceEmpty');
    const evidenceImage = document.getElementById('evidenceImage');
    const evidenceTitle = document.getElementById('evidenceTitle');
    const evidenceSeverity = document.getElementById('evidenceSeverity');
    const evidenceConfidence = document.getElementById('evidenceConfidence');
    const evidenceTimestamp = document.getElementById('evidenceTimestamp');
    const evidenceCoords = document.getElementById('evidenceCoords');
    const evidenceMission = document.getElementById('evidenceMission');
    const evidenceSource = document.getElementById('evidenceSource');
    const evidenceCluster = document.getElementById('evidenceCluster');
    const evidenceImageName = document.getElementById('evidenceImageName');
    const evidenceSummary = document.getElementById('evidenceSummary');
    const dashboardCountLabel = document.getElementById('dashboardCountLabel');

    const appConfig = window.APP_CONFIG || {};
    const AL_KHOBAR_LAT = 26.2833;
    const AL_KHOBAR_LON = 50.1983;
    const historyStorageKey = 'skylink_history_v2';
    const defaultLocation = { lat: 26.305, lon: 50.146 };

    let currentSelection = null;
    let currentImageBase64 = null;
    let currentImageDataUrl = null;
    let currentVideoUrl = null;
    let localHistory = [];
    let dashboardMarkers = [];
    let activeAnalysis = null;
    let selectedHistoryKey = '';
    let hasUserSelectedVlmMode = false;
    let hasUserSelectedVlmModel = false;

    let runtimeConfig = {
        BRIDGE_BASE_URL: String(appConfig.BRIDGE_BASE_URL || '').trim().replace(/\/+$/, ''),
        PUBLIC_BRIDGE_URL: String(appConfig.PUBLIC_BRIDGE_URL || '').trim().replace(/\/+$/, ''),
        ANALYZE_VIA_BRIDGE: appConfig.ANALYZE_VIA_BRIDGE !== false,
        DIRECT_MODEL_ENABLED: Boolean(appConfig.DIRECT_MODEL_ENABLED),
        TUNNEL_STATUS: String(appConfig.TUNNEL_STATUS || '').trim() || 'unknown',
        TUNNEL_ERROR: String(appConfig.TUNNEL_ERROR || '').trim(),
        MODEL_API_CONFIGURED: Boolean(appConfig.MODEL_API_CONFIGURED),
        ACTIVE_MODEL_API_URL: String(appConfig.ACTIVE_MODEL_API_URL || '').trim(),
        DEFAULT_MODEL_API_URL: String(appConfig.DEFAULT_MODEL_API_URL || '').trim(),
        DEFAULT_MODEL_API_KEY: String(appConfig.DEFAULT_MODEL_API_KEY || '').trim(),
        SERVER_SIDE_MODEL_KEY_CONFIGURED: Boolean(appConfig.SERVER_SIDE_MODEL_KEY_CONFIGURED),
        SERVER_SIDE_MODEL_KEY_MASKED: String(appConfig.SERVER_SIDE_MODEL_KEY_MASKED || '').trim(),
        MODEL_SERVER_STATUS: String(appConfig.MODEL_SERVER_STATUS || '').trim() || 'unknown',
        MODEL_SERVER_ERROR: String(appConfig.MODEL_SERVER_ERROR || '').trim(),
        MODEL_SERVER_PROVIDER: String(appConfig.MODEL_SERVER_PROVIDER || '').trim(),
        MODEL_SERVER_PUBLIC_URL: String(appConfig.MODEL_SERVER_PUBLIC_URL || '').trim(),
        MODEL_SERVER_REMOTE_HOST: String(appConfig.MODEL_SERVER_REMOTE_HOST || '').trim(),
        DEFAULT_VLM_MODE: String(appConfig.DEFAULT_VLM_MODE || 'local').trim(),
        VLM_MODE_OPTIONS: Array.isArray(appConfig.VLM_MODE_OPTIONS) ? appConfig.VLM_MODE_OPTIONS : ['local', 'api', 'disabled'],
        VLM_API_MODEL_OPTIONS: Array.isArray(appConfig.VLM_API_MODEL_OPTIONS) ? appConfig.VLM_API_MODEL_OPTIONS : [],
        VIDEO_ANALYSIS_ENABLED: Boolean(appConfig.VIDEO_ANALYSIS_ENABLED),
        VIDEO_ANALYSIS_ERROR: String(appConfig.VIDEO_ANALYSIS_ERROR || '').trim(),
        SUPABASE_CONFIGURED: Boolean(appConfig.SUPABASE_CONFIGURED)
    };

    function hasBridge() {
        return runtimeConfig.BRIDGE_BASE_URL.length > 0;
    }

    function bridgeAvailable() {
        return hasBridge();
    }

    function analyzeViaBridge() {
        return bridgeAvailable() && Boolean(runtimeConfig.ANALYZE_VIA_BRIDGE);
    }

    function bridgeUrl(path) {
        return `${runtimeConfig.BRIDGE_BASE_URL}${path}`;
    }

    function directApiUrl() {
        return runtimeConfig.DEFAULT_MODEL_API_URL;
    }

    function directApiKey() {
        return runtimeConfig.DEFAULT_MODEL_API_KEY;
    }

    function historyKey(record) {
        return `${record.timestamp || ''}|${record.image || ''}|${record.lat || ''}|${record.lon || ''}`;
    }

    function selectedVlmMode() {
        const checked = document.querySelector('input[name="vlmMode"]:checked');
        return checked ? checked.value : runtimeConfig.DEFAULT_VLM_MODE || 'local';
    }

    function selectedVlmModel() {
        const value = String(vlmModelSelect?.value || '').trim();
        return value;
    }

    function detectorOverrides() {
        return {
            detector_conf: parseNumericInput(detectorConfInput, 0.001),
            detector_iou: parseNumericInput(detectorIouInput, 0.90),
            detector_wbf_iou: parseNumericInput(detectorWbfIouInput, 0.40),
            detector_wbf_skip: parseNumericInput(detectorWbfSkipInput, 0.01),
            detector_final_threshold: parseNumericInput(detectorFinalThresholdInput, 0.03),
            detector_min_support: parseIntegerInput(detectorMinSupportInput, 1),
        };
    }

    function renderVlmModelOptions(force = false) {
        if (!vlmModelSelect) {
            return;
        }
        const options = Array.isArray(runtimeConfig.VLM_API_MODEL_OPTIONS) ? runtimeConfig.VLM_API_MODEL_OPTIONS : [];
        const previous = force ? '' : selectedVlmModel();
        vlmModelSelect.innerHTML = '<option value="">Use server default</option>';
        options.forEach(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = model;
            vlmModelSelect.appendChild(option);
        });
        if (previous && options.includes(previous)) {
            vlmModelSelect.value = previous;
        }
    }

    function syncVlmModelControl() {
        if (!vlmModelSelect) {
            return;
        }
        const isApi = selectedVlmMode() === 'api';
        vlmModelSelect.disabled = !isApi;
    }

    function applyDefaultVlmMode(force = false) {
        if (!force && hasUserSelectedVlmMode) {
            return;
        }
        const desired = runtimeConfig.DEFAULT_VLM_MODE || 'local';
        const target = document.querySelector(`input[name="vlmMode"][value="${desired}"]`);
        if (target) {
            target.checked = true;
        }
    }

    function updateConnectionPanel() {
        if (connectionMode) {
            if (runtimeConfig.DIRECT_MODEL_ENABLED && runtimeConfig.MODEL_API_CONFIGURED) {
                connectionMode.textContent = 'Direct model link active';
            } else if (analyzeViaBridge() && runtimeConfig.MODEL_API_CONFIGURED) {
                connectionMode.textContent = 'Bridge proxy active';
            } else if (runtimeConfig.MODEL_SERVER_STATUS && runtimeConfig.MODEL_SERVER_STATUS !== 'disabled') {
                connectionMode.textContent = 'Bridge bootstrapping remote model';
            } else {
                connectionMode.textContent = 'Waiting for model route';
            }
        }
        if (bridgeEndpoint) {
            bridgeEndpoint.textContent = runtimeConfig.BRIDGE_BASE_URL || 'Unavailable';
        }
        if (publicTunnel) {
            publicTunnel.textContent = runtimeConfig.PUBLIC_BRIDGE_URL || 'Starting quick tunnel...';
        }
        if (modelEndpoint) {
            modelEndpoint.textContent = runtimeConfig.ACTIVE_MODEL_API_URL || directApiUrl() || 'Not configured';
        }
        if (openPublicTunnelLink) {
            const target = runtimeConfig.PUBLIC_BRIDGE_URL || runtimeConfig.BRIDGE_BASE_URL || '';
            openPublicTunnelLink.href = target || '#';
            openPublicTunnelLink.classList.toggle('is-disabled', !target);
            openPublicTunnelLink.setAttribute('aria-disabled', target ? 'false' : 'true');
        }
        if (openModelLink) {
            const target = runtimeConfig.ACTIVE_MODEL_API_URL || directApiUrl() || '';
            openModelLink.href = target || '#';
            openModelLink.classList.toggle('is-disabled', !target);
            openModelLink.setAttribute('aria-disabled', target ? 'false' : 'true');
        }
        if (modelStatus) {
            const provider = runtimeConfig.MODEL_SERVER_PROVIDER ? ` (${runtimeConfig.MODEL_SERVER_PROVIDER})` : '';
            modelStatus.textContent = `${runtimeConfig.MODEL_SERVER_STATUS || 'unknown'}${provider}`;
            modelStatus.className = `runtime-value status-${String(runtimeConfig.MODEL_SERVER_STATUS || 'unknown').toLowerCase()}`;
        }
        if (modelApiKeyStatus) {
            modelApiKeyStatus.textContent = runtimeConfig.DIRECT_MODEL_ENABLED && directApiKey()
                ? `Loaded into frontend (${runtimeConfig.SERVER_SIDE_MODEL_KEY_MASKED || 'configured'})`
                : (runtimeConfig.SERVER_SIDE_MODEL_KEY_CONFIGURED
                    ? `Server-managed (${runtimeConfig.SERVER_SIDE_MODEL_KEY_MASKED || 'configured'})`
                    : (directApiKey() ? 'Loaded into frontend runtime' : 'Not configured'));
        }
        if (tunnelStatus) {
            tunnelStatus.textContent = runtimeConfig.TUNNEL_STATUS || 'unknown';
            tunnelStatus.className = `runtime-value status-${String(runtimeConfig.TUNNEL_STATUS || 'unknown').toLowerCase()}`;
        }
        if (supabaseStatus) {
            supabaseStatus.textContent = runtimeConfig.SUPABASE_CONFIGURED ? 'Configured' : 'Not configured';
            supabaseStatus.className = `runtime-value ${runtimeConfig.SUPABASE_CONFIGURED ? 'status-ready' : 'status-starting'}`;
        }
        if (tunnelError) {
            if (runtimeConfig.TUNNEL_ERROR) {
                tunnelError.textContent = runtimeConfig.TUNNEL_ERROR;
                tunnelError.classList.remove('hidden');
            } else {
                tunnelError.textContent = '';
                tunnelError.classList.add('hidden');
            }
        }
        if (modelError) {
            const combined = runtimeConfig.MODEL_SERVER_ERROR || runtimeConfig.VIDEO_ANALYSIS_ERROR;
            if (combined) {
                modelError.textContent = combined;
                modelError.classList.remove('hidden');
            } else {
                modelError.textContent = '';
                modelError.classList.add('hidden');
            }
        }
    }

    async function refreshRuntimeConfig() {
        if (!bridgeAvailable()) {
            updateConnectionPanel();
            return;
        }
        try {
            const response = await fetch(bridgeUrl('/api/runtime-config'));
            if (!response.ok) {
                throw new Error(`Runtime config request failed with ${response.status}`);
            }
            const payload = await response.json();
            runtimeConfig = {
                ...runtimeConfig,
                ...payload,
                BRIDGE_BASE_URL: String(payload.BRIDGE_BASE_URL || runtimeConfig.BRIDGE_BASE_URL || '').trim().replace(/\/+$/, ''),
                PUBLIC_BRIDGE_URL: String(payload.PUBLIC_BRIDGE_URL || runtimeConfig.PUBLIC_BRIDGE_URL || '').trim().replace(/\/+$/, ''),
                ACTIVE_MODEL_API_URL: String(payload.ACTIVE_MODEL_API_URL || '').trim(),
                DEFAULT_MODEL_API_URL: String(payload.DEFAULT_MODEL_API_URL || '').trim(),
                DEFAULT_MODEL_API_KEY: String(payload.DEFAULT_MODEL_API_KEY || '').trim(),
                TUNNEL_ERROR: String(payload.TUNNEL_ERROR || '').trim(),
                MODEL_SERVER_ERROR: String(payload.MODEL_SERVER_ERROR || '').trim(),
                DEFAULT_VLM_MODE: String(payload.DEFAULT_VLM_MODE || runtimeConfig.DEFAULT_VLM_MODE || 'local').trim(),
                VIDEO_ANALYSIS_ERROR: String(payload.VIDEO_ANALYSIS_ERROR || '').trim(),
                VLM_API_MODEL_OPTIONS: Array.isArray(payload.VLM_API_MODEL_OPTIONS) ? payload.VLM_API_MODEL_OPTIONS : runtimeConfig.VLM_API_MODEL_OPTIONS
            };
            applyDefaultVlmMode();
            if (!hasUserSelectedVlmModel) {
                renderVlmModelOptions(true);
            }
        } catch (error) {
            console.error('Failed to refresh runtime config', error);
        }
        updateConnectionPanel();
        syncVlmModelControl();
        checkInputs();
    }

    function resetPreview() {
        imagePreviewContainer.classList.add('hidden');
        videoPreviewContainer.classList.add('hidden');
        imagePreview.src = '';
        videoPreview.pause();
        videoPreview.removeAttribute('src');
        videoPreview.load();
        currentImageBase64 = null;
        currentImageDataUrl = null;
        if (currentVideoUrl) {
            URL.revokeObjectURL(currentVideoUrl);
            currentVideoUrl = null;
        }
    }

    function showError(msg) {
        errorContainer.textContent = msg;
        errorContainer.classList.remove('hidden');
    }

    function clearError() {
        errorContainer.textContent = '';
        errorContainer.classList.add('hidden');
    }

    function setButtonState() {
        if (!currentSelection) {
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = 'Analyze Media';
            return;
        }
        if (currentSelection.kind === 'video' && !hasBridge()) {
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = 'Video Analysis Requires Bridge';
            return;
        }
        const imageReady = currentSelection.kind === 'image' && (
            (analyzeViaBridge() && runtimeConfig.MODEL_API_CONFIGURED) ||
            Boolean(directApiUrl())
        );
        const videoReady = currentSelection.kind === 'video' && hasBridge() && runtimeConfig.VIDEO_ANALYSIS_ENABLED;
        analyzeBtn.disabled = !(imageReady || videoReady);
        analyzeBtn.textContent = currentSelection.kind === 'video' ? 'Analyze Video' : 'Analyze Photo';
    }

    function checkInputs() {
        setButtonState();
    }

    function handleFileSelect(file) {
        clearError();
        resetPreview();
        currentSelection = null;
        activeAnalysis = null;

        if (!file) {
            checkInputs();
            return;
        }

        if (file.type.startsWith('image/')) {
            const reader = new FileReader();
            reader.onload = function (e) {
                currentImageDataUrl = e.target.result;
                currentImageBase64 = String(e.target.result).split(',')[1];
                currentSelection = {
                    kind: 'image',
                    file,
                    previewUrl: currentImageDataUrl
                };
                imagePreview.src = currentImageDataUrl;
                imagePreviewContainer.classList.remove('hidden');
                checkInputs();
            };
            reader.readAsDataURL(file);
            return;
        }

        if (file.type.startsWith('video/')) {
            currentVideoUrl = URL.createObjectURL(file);
            currentSelection = {
                kind: 'video',
                file,
                previewUrl: currentVideoUrl
            };
            videoPreview.src = currentVideoUrl;
            videoPreviewContainer.classList.remove('hidden');
            checkInputs();
            return;
        }

        showError('Please select an image or video file.');
        checkInputs();
    }

    function parseNumericInput(element, fallback) {
        const parsed = Number.parseFloat(String(element.value || '').trim());
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function parseIntegerInput(element, fallback) {
        const parsed = Number.parseInt(String(element.value || '').trim(), 10);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function ensureImageSource(value) {
        const normalized = String(value || '').trim();
        if (!normalized) return '';
        if (normalized.startsWith('data:image') || normalized.startsWith('http')) {
            return normalized;
        }

        // Comprehensive Base64 detection
        // 1. Check for known Base64 starters (JPEG: /9j/, PNG: iVBO, etc.)
        // 2. Check for length and character set (no spaces, and not just a short path)
        const isLikelyBase64 = (
            normalized.startsWith('/9j/') ||
            normalized.startsWith('iVBOR') ||
            (normalized.length > 500 && !normalized.includes(' ') && !normalized.includes('\\'))
        );

        if (isLikelyBase64) {
            // Ensure data URI prefix is present
            if (normalized.startsWith('data:')) return normalized;
            return `data:image/jpeg;base64,${normalized}`;
        }

        // It's likely a path. Ensure it's absolute for the bridge.
        if (normalized.startsWith('/')) {
            // If we have a bridge URL configured, use it
            if (typeof bridgeUrl === 'function') {
                return bridgeUrl(normalized);
            }
        }

        // Fallback for relative paths or malformed strings
        return normalized;
    }

    function drawImageOnCanvas(source) {
        if (!source) {
            if (resultImage) {
                resultImage.removeAttribute('src');
            }
            return;
        }
        if (resultImage) {
            resultImage.src = source;
        }
        const ctx = canvas.getContext('2d');
        const img = new Image();
        img.onload = () => {
            canvas.width = img.width;
            canvas.height = img.height;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0);
        };
        img.onerror = () => {
            console.error('Failed to render annotated image source.');
        };
        img.src = source;
    }

    function renderBoxesTable(boxes) {
        boxesTableBody.innerHTML = '';
        if (!boxes || boxes.length === 0) {
            boxesTableBody.innerHTML = '<tr><td colspan="4" style="text-align:center">No features detected.</td></tr>';
            return;
        }
        boxes.forEach((box, idx) => {
            const severity = (box.severity || 'low').toLowerCase();
            const confidence = typeof box.confidence === 'number' ? `${(box.confidence * 100).toFixed(1)}%` : '-';
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight:700">${box.id || idx + 1}</td>
                <td>${box.label || box.class || 'Defect'}</td>
                <td class="severity-${severity}">${box.severity || 'Low'}</td>
                <td>${confidence}</td>
            `;
            boxesTableBody.appendChild(tr);
        });
    }

    function renderActions(boxes) {
        actionsList.innerHTML = '';
        const highCount = boxes.filter(b => String(b.severity || '').toLowerCase() === 'high').length;
        const mediumCount = boxes.filter(b => ['medium', 'moderate'].includes(String(b.severity || '').toLowerCase())).length;

        const actions = [];
        if (highCount > 0) {
            actions.push(`Dispatch urgent maintenance for ${highCount} high-severity defect(s).`);
        }
        if (mediumCount > 0) {
            actions.push(`Schedule follow-up inspection for ${mediumCount} medium-severity defect(s).`);
        }
        if (boxes.length > 0) {
            actions.push('Review ensemble detections against the annotated image before closure.');
        } else {
            actions.push('No visible damage was detected. Keep routine monitoring active.');
        }

        actions.forEach(text => {
            const li = document.createElement('li');
            li.textContent = text;
            actionsList.appendChild(li);
        });
    }

    function renderReport(summary, markdown, boxes, debug, mediaSource, metaText, viewerTitle) {
        emptyState.classList.add('hidden');
        resultSection.classList.remove('hidden');
        reportSummary.textContent = summary || 'Analysis complete';
        resultMetaLine.textContent = metaText || '';
        resultViewerTitle.textContent = viewerTitle || 'Annotated Road View';
        markdownContainer.innerHTML = marked.parse(markdown || '_No report text returned._');
        detectorDebugPanel.textContent = JSON.stringify(debug || {}, null, 2);
        renderBoxesTable(boxes || []);
        renderActions(boxes || []);
        drawImageOnCanvas(mediaSource);
    }

    function summarizeVideoSession(session) {
        return `${session.processed_count} frames processed, ${session.frames_with_detections} with detections`;
    }

    function selectBestFrame(session) {
        if (!session.frames || session.frames.length === 0) {
            return null;
        }
        const withBoxes = session.frames.find(frame => (frame.boxes || []).length > 0);
        return withBoxes || session.frames[0];
    }

    function renderVideoFrameButtons(session, selectedIndex) {
        videoFramesStrip.innerHTML = '';
        if (!session.frames || session.frames.length === 0) {
            videoFramesStrip.classList.add('hidden');
            return;
        }
        videoFramesStrip.classList.remove('hidden');

        session.frames.forEach((frame, index) => {
            const button = document.createElement('button');
            button.className = `frame-chip ${index === selectedIndex ? 'active' : ''}`;
            const thumbRaw = frame.thumb_url || frame.frame_url || '';
            const thumb = (thumbRaw.length > 200 && thumbRaw.startsWith('/9j/') && !thumbRaw.startsWith('data:'))
                ? `data:image/jpeg;base64,${thumbRaw}`
                : thumbRaw;
            button.innerHTML = `
                <span class="frame-chip-index">F${index + 1}</span>
                ${thumb ? `<img src="${thumb}" alt="Frame ${index + 1}"/>` : '<span class="frame-chip-placeholder">No Preview</span>'}
                <span class="frame-chip-meta">${(frame.boxes || []).length} box(es)</span>
            `;
            button.addEventListener('click', () => {
                renderVideoAnalysis(session, index);
            });
            videoFramesStrip.appendChild(button);
        });
    }

    function renderVideoAnalysis(session, selectedIndex = 0) {
        activeAnalysis = { kind: 'video', session, selectedIndex };
        const frame = session.frames[selectedIndex];
        if (!frame) {
            showError('No processed frames were returned from the video pipeline.');
            return;
        }
        renderVideoFrameButtons(session, selectedIndex);
        const mediaSource = ensureImageSource(frame.annotated_url || frame.frame_url || frame.thumb_url || '');
        const resolvedMode = frame.detector_debug?.resolved_vlm_mode || selectedVlmMode();
        const metaText = `Video session • frame ${selectedIndex + 1}/${session.frames.length} • ${frame.processing_seconds || '-'}s • VLM ${resolvedMode}`;
        renderReport(
            frame.summary || summarizeVideoSession(session),
            frame.report_markdown || '_No per-frame report returned._',
            frame.boxes || [],
            frame.detector_debug || {},
            mediaSource,
            metaText,
            'Annotated Video Frame'
        );
        finalTime.textContent = `(${Number(session.elapsed_seconds || 0).toFixed(1)}s session)`;
        reportSummary.textContent = summarizeVideoSession(session);
    }

    function renderImageAnalysis(report, durationSeconds) {
        videoFramesStrip.classList.add('hidden');
        videoFramesStrip.innerHTML = '';
        const mediaSource =
            ensureImageSource(report.annotated_image_b64)
            || ensureImageSource(report.persisted_finding?.local_image_url)
            || ensureImageSource(report.persisted_finding?.image)
            || currentImageDataUrl;
        const resolvedMode = report.detector_debug?.resolved_vlm_mode || selectedVlmMode();
        const metaText = `Photo analysis • detector ensemble • VLM ${resolvedMode} • ${report.boxes?.length || 0} box(es)`;
        renderReport(
            report.summary || 'Analysis complete',
            report.report_markdown || '_No report text returned._',
            report.boxes || [],
            report.detector_debug || {},
            mediaSource,
            metaText,
            'Annotated Road View'
        );
        finalTime.textContent = `(${durationSeconds.toFixed(1)}s)`;
    }

    async function analyzeImage() {
        const payload = {
            image_b64: currentImageBase64,
            location: [defaultLocation.lat, defaultLocation.lon],
            api_key: directApiKey(),
            api_url: directApiUrl(),
            vlm_mode: selectedVlmMode(),
            vlm_model: selectedVlmModel(),
            ...detectorOverrides(),
            mission_name: missionNameInput.value.trim() || currentSelection?.file?.name || 'SkyLink Photo Mission',
            persist_db: persistDbToggle.checked,
            image_name: currentSelection?.file?.name || '',
        };

        let response;
        if (analyzeViaBridge()) {
            response = await fetch(bridgeUrl('/api/analyze'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            response = await fetch(directApiUrl(), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(directApiKey() ? { 'X-API-Key': directApiKey() } : {})
                },
                body: JSON.stringify({
                    image_b64: currentImageBase64,
                    location: [defaultLocation.lat, defaultLocation.lon],
                    vlm_mode: selectedVlmMode(),
                    vlm_model: selectedVlmModel(),
                    ...detectorOverrides()
                })
            });
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Server error: ${response.status} ${response.statusText}`);
        }
        const result = await response.json();
        const data = result.data || result;
        const report = data.report || data.vlm_report || data;
        if (data.persisted_finding) {
            report.persisted_finding = data.persisted_finding;
        }
        if (typeof data.persisted_to_supabase !== 'undefined') {
            report.persisted_to_supabase = Boolean(data.persisted_to_supabase);
        }
        return report;
    }

    async function analyzeVideo() {
        if (!hasBridge()) {
            throw new Error('Video analysis requires the bridge server path.');
        }

        const formData = new FormData();
        formData.append('video', currentSelection.file);
        formData.append('mission_name', missionNameInput.value.trim() || currentSelection.file.name || 'SkyLink Video Mission');
        formData.append('vlm_mode', selectedVlmMode());
        formData.append('vlm_model', selectedVlmModel());
        formData.append('detector_conf', String(parseNumericInput(detectorConfInput, 0.001)));
        formData.append('detector_iou', String(parseNumericInput(detectorIouInput, 0.90)));
        formData.append('detector_wbf_iou', String(parseNumericInput(detectorWbfIouInput, 0.40)));
        formData.append('detector_wbf_skip', String(parseNumericInput(detectorWbfSkipInput, 0.01)));
        formData.append('detector_final_threshold', String(parseNumericInput(detectorFinalThresholdInput, 0.03)));
        formData.append('detector_min_support', String(parseIntegerInput(detectorMinSupportInput, 1)));
        formData.append('overlap_fraction', String(parseNumericInput(videoOverlapInput, 0.10)));
        formData.append('dedup_distance', String(parseIntegerInput(videoDedupInput, 4)));
        formData.append('max_frames', String(parseIntegerInput(videoMaxFramesInput, 24)));
        formData.append('persist_db', persistDbToggle.checked ? 'true' : 'false');

        const response = await fetch(bridgeUrl('/api/analyze-video'), {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Video analysis failed with ${response.status}`);
        }
        return response.json();
    }

    async function trackHistoricalAnalysis(boxes, summary, thumbUrl, location = defaultLocation, metadata = {}) {
        const severityStatus = boxes.some(b => String(b.severity || '').toLowerCase() === 'high')
            ? 'High Severity'
            : (boxes.length > 0 ? 'Moderate' : 'Low Severity');

        const record = {
            lat: location.lat,
            lon: location.lon,
            severity: severityStatus,
            summary,
            confidence: _maxConfidence(boxes),
            image: thumbUrl,
            timestamp: new Date().toISOString(),
            mission_id: metadata.mission_id || '',
            mission_name: metadata.mission_name || '',
            image_id: metadata.image_id || '',
            image_name: metadata.image_name || '',
            source: metadata.source || 'bridge',
            box_count: Number(metadata.box_count || boxes.length || 0),
            defect_types: Array.isArray(metadata.defect_types) ? metadata.defect_types : [],
            cluster_key: metadata.cluster_key || metadata.mission_id || metadata.mission_name || 'standalone',
            persisted_to_supabase: Boolean(metadata.persisted_to_supabase)
        };

        if (hasBridge()) {
            try {
                await fetch(bridgeUrl('/api/history'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(record)
                });
                await loadHistoricalAnalysis();
                return;
            } catch (e) {
                console.error('Failed to save history to bridge', e);
            }
        }

        localHistory.push(record);
        localHistory = localHistory.slice(-50);
        localStorage.setItem(historyStorageKey, JSON.stringify(localHistory));
        updateDashboardKPI();
    }

    function _maxConfidence(boxes) {
        if (!boxes || boxes.length === 0) return 0;
        return boxes.reduce((max, box) => Math.max(max, Number(box.confidence || 0)), 0);
    }

    function getFilteredHistory() {
        const severity = String(dashboardSeverityFilter?.value || 'all').toLowerCase();
        const maxAgeDays = Number.parseInt(String(dashboardTimeFilter?.value || 'all'), 10);
        const minConfidence = Number.parseFloat(String(dashboardConfidenceFilter?.value || '0'));
        const now = Date.now();

        return localHistory.filter(record => {
            const normalizedSeverity = String(record.severity || '').toLowerCase();
            const severityPass = severity === 'all'
                || (severity === 'high' && normalizedSeverity.includes('high'))
                || (severity === 'moderate' && normalizedSeverity.includes('moderate'))
                || (severity === 'low' && normalizedSeverity.includes('low'));

            const confidencePass = Number(record.confidence || 0) >= (Number.isFinite(minConfidence) ? minConfidence : 0);

            let timePass = true;
            if (Number.isFinite(maxAgeDays)) {
                const ts = Date.parse(record.timestamp || '');
                timePass = Number.isFinite(ts) ? (now - ts) <= maxAgeDays * 86400000 : false;
            }

            return severityPass && confidencePass && timePass;
        });
    }

    function applySeverityClass(element, severityText) {
        if (!element) return;
        const normalized = String(severityText || '').toLowerCase();
        element.classList.remove('high', 'moderate', 'low');
        if (normalized.includes('high') || normalized.includes('critical')) {
            element.classList.add('high');
        } else if (normalized.includes('moderate')) {
            element.classList.add('moderate');
        } else if (normalized.includes('low')) {
            element.classList.add('low');
        }
    }

    function renderEvidenceDetail(record) {
        if (!record) {
            selectedHistoryKey = '';
            if (evidenceEmpty) evidenceEmpty.classList.remove('hidden');
            if (evidenceImage) evidenceImage.removeAttribute('src');
            if (evidenceTitle) evidenceTitle.textContent = 'No finding selected';
            if (evidenceSeverity) {
                evidenceSeverity.textContent = 'No Evidence';
                applySeverityClass(evidenceSeverity, '');
            }
            if (evidenceConfidence) evidenceConfidence.textContent = '-';
            if (evidenceTimestamp) evidenceTimestamp.textContent = '-';
            if (evidenceCoords) evidenceCoords.textContent = '-';
            if (evidenceMission) evidenceMission.textContent = '-';
            if (evidenceSource) evidenceSource.textContent = '-';
            if (evidenceCluster) evidenceCluster.textContent = '-';
            if (evidenceImageName) evidenceImageName.textContent = '-';
            if (evidenceSummary) evidenceSummary.textContent = 'History-backed detections will appear here as you analyze images or videos.';
            return;
        }

        selectedHistoryKey = historyKey(record);
        if (evidenceEmpty) evidenceEmpty.classList.add('hidden');

        let imgSrc = record.image || '';
        if (imgSrc.length > 200 && imgSrc.startsWith('/9j/') && !imgSrc.startsWith('data:')) {
            imgSrc = `data:image/jpeg;base64,${imgSrc}`;
        }
        if (evidenceImage) evidenceImage.src = imgSrc;
        if (evidenceTitle) evidenceTitle.textContent = record.summary || 'Detection';
        if (evidenceSeverity) {
            evidenceSeverity.textContent = record.severity || 'Unknown';
            applySeverityClass(evidenceSeverity, record.severity);
        }
        if (evidenceConfidence) {
            const confidence = Number(record.confidence || 0);
            evidenceConfidence.textContent = Number.isFinite(confidence) && confidence > 0
                ? `${(confidence * 100).toFixed(1)}% conf`
                : 'Unscored';
        }
        if (evidenceTimestamp) {
            evidenceTimestamp.textContent = record.timestamp
                ? new Date(record.timestamp).toLocaleString()
                : '-';
        }
        if (evidenceCoords) {
            evidenceCoords.textContent = `${Number(record.lat || 0).toFixed(4)}, ${Number(record.lon || 0).toFixed(4)}`;
        }
        if (evidenceMission) {
            evidenceMission.textContent = record.mission_name || record.mission_id || 'Standalone';
        }
        if (evidenceSource) {
            evidenceSource.textContent = record.persisted_to_supabase ? 'Supabase' : (record.source || 'Bridge');
        }
        if (evidenceCluster) {
            evidenceCluster.textContent = `${record.cluster_size || 1} item(s)`;
        }
        if (evidenceImageName) {
            evidenceImageName.textContent = record.image_name || 'Rendered evidence';
        }
        if (evidenceSummary) {
            evidenceSummary.textContent = record.summary || 'No summary available.';
        }
    }

    function recenterDashboardMap(records) {
        if (!window.dashboardMap) return;
        const usable = (records || []).filter(record => Number.isFinite(Number(record.lat)) && Number.isFinite(Number(record.lon)));
        if (usable.length === 0) {
            window.dashboardMap.setView([AL_KHOBAR_LAT, AL_KHOBAR_LON], 12);
            return;
        }
        if (usable.length === 1) {
            window.dashboardMap.setView([usable[0].lat, usable[0].lon], 15);
            return;
        }
        const bounds = L.latLngBounds(usable.map(record => [record.lat, record.lon]));
        window.dashboardMap.fitBounds(bounds.pad(0.18));
    }

    async function loadHistoricalAnalysis() {
        if (hasBridge()) {
            try {
                const response = await fetch(bridgeUrl('/api/findings'));
                if (!response.ok) {
                    throw new Error(`Findings request failed with ${response.status}`);
                }
                localHistory = await response.json();
            } catch (error) {
                console.error('Failed to load bridge findings, falling back to local history', error);
                try {
                    const historyResponse = await fetch(bridgeUrl('/api/history'));
                    if (!historyResponse.ok) {
                        throw new Error(`History request failed with ${historyResponse.status}`);
                    }
                    localHistory = await historyResponse.json();
                } catch (_) {
                    try {
                        localHistory = JSON.parse(localStorage.getItem(historyStorageKey) || '[]');
                    } catch (__){
                        localHistory = [];
                    }
                }
            }
        } else {
            try {
                localHistory = JSON.parse(localStorage.getItem(historyStorageKey) || '[]');
            } catch (_) {
                localHistory = [];
            }
        }
        updateDashboardKPI();
    }

    function updateDashboardKPI() {
        const filteredHistory = getFilteredHistory();
        document.getElementById('kpiTotal').textContent = filteredHistory.length;
        const criticalCount = filteredHistory.filter(h => h.severity === 'High Severity').length;
        document.getElementById('kpiCritical').textContent = criticalCount;
        const avgConf = filteredHistory.length
            ? (filteredHistory.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / filteredHistory.length)
            : 0;
        document.getElementById('kpiAvgConf').textContent = avgConf > 0 ? `${(avgConf * 100).toFixed(1)}%` : 'Moderate';
        if (dashboardCountLabel) {
            dashboardCountLabel.textContent = `${filteredHistory.length} record${filteredHistory.length === 1 ? '' : 's'}`;
        }

        if (window.dashboardMap) {
            dashboardMarkers.forEach(m => window.dashboardMap.removeLayer(m));
            dashboardMarkers = [];

            filteredHistory.forEach(record => {
                let color = '#22c55e';
                if (record.severity === 'High Severity') color = '#ef4444';
                else if (record.severity === 'Moderate') color = '#f59e0b';

                const marker = L.circleMarker([record.lat, record.lon], {
                    radius: 8,
                    fillColor: color,
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 0.9
                }).bindPopup(`<b>${record.severity}</b><br/>${record.summary}`).addTo(window.dashboardMap);
                marker.on('click', () => {
                    renderEvidenceDetail(record);
                    updateDashboardKPI();
                });
                dashboardMarkers.push(marker);
            });
        }

        const grid = document.getElementById('historyGrid');
        if (grid) {
            grid.innerHTML = '';
            if (filteredHistory.length === 0) {
                const emptyCard = document.createElement('div');
                emptyCard.className = 'drawer-summary';
                emptyCard.textContent = 'No evidence matches the current filters yet.';
                grid.appendChild(emptyCard);
            }
            [...filteredHistory].reverse().forEach(record => {
                const card = document.createElement('div');
                const recordKey = historyKey(record);
                card.className = `history-card ${selectedHistoryKey === recordKey ? 'active' : ''}`;

                const sevClass = record.severity === 'High Severity' ? 'high'
                    : record.severity === 'Moderate' ? 'moderate' : 'low';

                card.innerHTML = `
                    <img src="${record.image || 'https://via.placeholder.com/300x160?text=No+Image'}" alt="Analysis" />
                    <div class="history-card-content">
                        <div class="history-date">${new Date(record.timestamp).toLocaleString()}</div>
                        <div class="history-severity ${sevClass}">${record.severity}</div>
                        <div class="history-date">${record.mission_name || record.mission_id || 'Standalone'} • ${record.cluster_size || 1} item cluster</div>
                        <div class="history-summary">${record.summary}</div>
                    </div>
                `;
                card.addEventListener('click', () => {
                    renderEvidenceDetail(record);
                    if (window.dashboardMap) {
                        window.dashboardMap.setView([record.lat, record.lon], Math.max(window.dashboardMap.getZoom(), 15));
                    }
                    updateDashboardKPI();
                });
                grid.appendChild(card);
            });
        }

        const selectedStillVisible = filteredHistory.some(record => historyKey(record) === selectedHistoryKey);
        if (!selectedStillVisible) {
            renderEvidenceDetail(filteredHistory[0] || null);
        } else {
            const selected = filteredHistory.find(record => historyKey(record) === selectedHistoryKey);
            renderEvidenceDetail(selected || null);
        }
    }

    function initDashboardMap() {
        window.dashboardMap = L.map('kpiMap').setView([AL_KHOBAR_LAT, AL_KHOBAR_LON], 12);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO'
        }).addTo(window.dashboardMap);
        loadHistoricalAnalysis();
    }

    function initMissionMap() {
        const KFUPM_LAT = 26.3073;
        const KFUPM_LON = 50.1456;

        window.missionMap = L.map('map').setView([KFUPM_LAT, KFUPM_LON], 16);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            maxZoom: 20
        }).addTo(window.missionMap);

        const droneIcon = L.divIcon({
            className: 'drone-marker',
            html: '<div style="font-size:24px; text-shadow:0 0 10px #4ade80;">✈️</div>',
            iconSize: [24, 24],
            iconAnchor: [12, 12]
        });

        const droneMarker = L.marker([KFUPM_LAT, KFUPM_LON], { icon: droneIcon }).addTo(window.missionMap);
        const pathLine = L.polyline([], { color: '#818cf8', weight: 3, dashArray: '5, 10' }).addTo(window.missionMap);
        let angle = 0;

        setInterval(() => {
            if (document.getElementById('mission').classList.contains('active')) {
                const radius = 0.002;
                const newLat = KFUPM_LAT + Math.sin(angle) * radius;
                const newLon = KFUPM_LON + Math.cos(angle) * (radius * 1.5);
                droneMarker.setLatLng([newLat, newLon]);
                pathLine.addLatLng([newLat, newLon]);
                window.missionMap.panTo([newLat, newLon], { animate: true });
                angle += 0.02;
            }
        }, 2000);
    }

    function initWaypointMap() {
        const KFUPM_LAT = 26.3048;
        const KFUPM_LON = 50.1458;

        window.waypointMap = L.map('waypointMap', { zoomControl: true }).setView([KFUPM_LAT, KFUPM_LON], 17);
        setTimeout(() => window.waypointMap.invalidateSize(), 500);

        L.tileLayer('https://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}', {
            maxZoom: 22,
            subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
        }).addTo(window.waypointMap);

        let waypoints = [];
        let polyline = L.polyline([], { color: '#c084fc', weight: 4 }).addTo(window.waypointMap);
        let polygon = L.polygon([], { color: '#c084fc', weight: 2, fillColor: '#818cf8', fillOpacity: 0.2 }).addTo(window.waypointMap);
        let markers = [];

        window.waypointMap.on('click', (e) => {
            const latlng = e.latlng;
            waypoints.push(latlng);

            const marker = L.circleMarker(latlng, {
                radius: 6,
                fillColor: waypoints.length === 1 ? '#22c55e' : '#c084fc',
                color: '#fff',
                weight: 2,
                fillOpacity: 1
            }).bindTooltip(`WP ${waypoints.length}`, { permanent: true, direction: 'right' }).addTo(window.waypointMap);

            markers.push(marker);
            updatePath();
        });

        document.getElementById('btnClearWaypoints').addEventListener('click', () => {
            waypoints = [];
            markers.forEach(m => window.waypointMap.removeLayer(m));
            markers = [];
            polyline.setLatLngs([]);
            polygon.setLatLngs([]);
            document.getElementById('btnRTL').disabled = true;
            updateAreaDisplay(0);
        });

        document.getElementById('btnRTL').addEventListener('click', () => {
            if (waypoints.length > 2) {
                waypoints.push(waypoints[0]);
                updatePath();
                polygon.setLatLngs(waypoints);
                calculateAndEnforceArea(waypoints);
            }
        });

        function updatePath() {
            polyline.setLatLngs(waypoints);
            document.getElementById('btnRTL').disabled = waypoints.length < 3;
        }

        function calculateAndEnforceArea(points) {
            let areaSqMeters = 0;
            if (points.length > 2 && typeof L.GeometryUtil !== 'undefined') {
                areaSqMeters = L.GeometryUtil.geodesicArea(points);
            } else {
                const R = 6378137;
                let area = 0;
                const numPoints = points.length;
                for (let i = 0; i < numPoints; i++) {
                    const j = (i + 1) % numPoints;
                    const p1 = points[i];
                    const p2 = points[j];
                    area += ((p2.lng - p1.lng) * Math.PI / 180) *
                        (2 + Math.sin(p1.lat * Math.PI / 180) + Math.sin(p2.lat * Math.PI / 180));
                }
                areaSqMeters = Math.abs(area * R * R / 2.0);
            }

            areaSqMeters = areaSqMeters * 0.25;
            updateAreaDisplay(areaSqMeters);
        }

        function updateAreaDisplay(area) {
            const roundedArea = Math.round(area * 10) / 10;
            const areaLabel = document.getElementById('areaValue');
            const warning = document.getElementById('areaWarning');
            areaLabel.textContent = `${roundedArea} m²`;

            if (roundedArea > 50) {
                areaLabel.style.color = 'var(--error)';
                warning.classList.remove('hidden');
            } else {
                areaLabel.style.color = 'var(--text-primary)';
                warning.classList.add('hidden');
            }
        }
    }

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        fileLabel.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        fileLabel.addEventListener(eventName, () => fileLabel.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        fileLabel.addEventListener(eventName, () => fileLabel.classList.remove('dragover'), false);
    });

    fileLabel.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            imageInput.files = files;
            handleFileSelect(files[0]);
        }
    }

    imageInput.addEventListener('change', function () {
        if (this.files && this.files[0]) {
            handleFileSelect(this.files[0]);
        }
    });

    [dashboardSeverityFilter, dashboardTimeFilter, dashboardConfidenceFilter].forEach(input => {
        if (!input) return;
        input.addEventListener('change', () => {
            updateDashboardKPI();
            recenterDashboardMap(getFilteredHistory());
        });
    });

    if (recenterMapBtn) {
        recenterMapBtn.addEventListener('click', () => {
            recenterDashboardMap(getFilteredHistory());
        });
    }

    if (resetDashboardFilters) {
        resetDashboardFilters.addEventListener('click', () => {
            if (dashboardSeverityFilter) dashboardSeverityFilter.value = 'all';
            if (dashboardTimeFilter) dashboardTimeFilter.value = 'all';
            if (dashboardConfidenceFilter) dashboardConfidenceFilter.value = '0';
            updateDashboardKPI();
            recenterDashboardMap(getFilteredHistory());
        });
    }

    if (toggleEvidenceDrawerBtn && evidenceDrawer) {
        toggleEvidenceDrawerBtn.addEventListener('click', () => {
            evidenceDrawer.classList.toggle('collapsed');
        });
    }

    if (refreshRuntimeBtn) {
        refreshRuntimeBtn.addEventListener('click', () => {
            void refreshRuntimeConfig();
        });
    }

    document.querySelectorAll('input[name="vlmMode"]').forEach(input => {
        input.addEventListener('change', () => {
            hasUserSelectedVlmMode = true;
            syncVlmModelControl();
            checkInputs();
            if (activeAnalysis && activeAnalysis.kind === 'video') {
                resultMetaLine.textContent = resultMetaLine.textContent.replace(/VLM [^•]+/, `VLM ${selectedVlmMode()}`);
            }
        });
    });

    if (vlmModelSelect) {
        vlmModelSelect.addEventListener('change', () => {
            hasUserSelectedVlmModel = true;
        });
    }

    analyzeBtn.addEventListener('click', async () => {
        clearError();
        loadingIndicator.classList.remove('hidden');
        analyzeBtn.disabled = true;
        finalTime.textContent = '';

        const activeTimerSpan = document.getElementById('activeTimer');
        let seconds = 0;
        activeTimerSpan.textContent = '0';
        const timerInterval = setInterval(() => {
            seconds += 1;
            activeTimerSpan.textContent = seconds;
        }, 1000);

        const startTime = performance.now();

        try {
            if (!currentSelection) {
                throw new Error('Select an image or video first.');
            }

            if (currentSelection.kind === 'video') {
                const session = await analyzeVideo();
                const bestIndex = Math.max(0, session.frames.findIndex(frame => (frame.boxes || []).length > 0));
                renderVideoAnalysis(session, bestIndex);
                const bestFrame = selectBestFrame(session);
                if (bestFrame) {
                    await trackHistoricalAnalysis(
                        bestFrame.boxes || [],
                        summarizeVideoSession(session),
                        bestFrame.thumb_url || bestFrame.frame_url,
                        defaultLocation,
                        bestFrame.finding_record || {}
                    );
                }
            } else {
                const report = await analyzeImage();
                renderImageAnalysis(report, (performance.now() - startTime) / 1000);
                await trackHistoricalAnalysis(
                    report.boxes || [],
                    report.summary || 'Analysis complete',
                    report.persisted_finding?.image || ensureImageSource(report.annotated_image_b64) || currentImageDataUrl,
                    defaultLocation,
                    report.persisted_finding || {}
                );
            }
            resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (err) {
            console.error(err);
            showError(err.message || 'An error occurred while contacting the analysis backend.');
        } finally {
            clearInterval(timerInterval);
            const duration = ((performance.now() - startTime) / 1000).toFixed(1);
            if (finalTime.textContent === '') {
                finalTime.textContent = `(${duration}s)`;
            }
            loadingIndicator.classList.add('hidden');
            analyzeBtn.disabled = false;
            checkInputs();
        }
    });

    const tabs = document.querySelectorAll('.nav-links li');
    const tabContents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            tab.classList.add('active');
            const targetId = tab.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');

            setTimeout(() => {
                if (targetId === 'mission' && window.missionMap) {
                    window.missionMap.invalidateSize();
                }
                if (targetId === 'waypoints' && window.waypointMap) {
                    window.waypointMap.invalidateSize();
                }
                if (targetId === 'dashboard' && window.dashboardMap) {
                    window.dashboardMap.invalidateSize();
                }
            }, 300);
        });
    });

    setTimeout(() => {
        if (typeof L !== 'undefined') {
            initMissionMap();
            initWaypointMap();
            initDashboardMap();
        }
    }, 500);

    applyDefaultVlmMode(true);
    renderVlmModelOptions(true);
    updateConnectionPanel();
    syncVlmModelControl();
    void refreshRuntimeConfig();
    setInterval(() => {
        void refreshRuntimeConfig();
    }, 5000);
    checkInputs();
});

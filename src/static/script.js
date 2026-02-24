document.addEventListener('DOMContentLoaded', () => {
    const apiKeyInput = document.getElementById('apiKey');
    const apiUrlInput = document.getElementById('apiUrl');
    const imageInput = document.getElementById('imageInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const fileLabel = document.querySelector('.file-label');

    const loadingIndicator = document.getElementById('loadingIndicator');
    const errorContainer = document.getElementById('errorContainer');
    const resultSection = document.getElementById('resultSection');

    let currentImageBase64 = null;
    let currentImageDataUrl = null;

    // Handle drag and drop styling
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

    imageInput.addEventListener('change', function (e) {
        if (this.files && this.files[0]) {
            handleFileSelect(this.files[0]);
        }
    });

    function handleFileSelect(file) {
        if (!file.type.match('image.*')) {
            showError("Please select an image file.");
            return;
        }

        const reader = new FileReader();
        reader.onload = function (e) {
            imagePreview.src = e.target.result;
            imagePreviewContainer.classList.remove('hidden');

            // Store full data URL for canvas rendering
            currentImageDataUrl = e.target.result;
            // Extract base64 part (remove data:image/jpeg;base64,)
            currentImageBase64 = e.target.result.split(',')[1];

            checkInputs();
        }
        reader.readAsDataURL(file);
    }

    [apiKeyInput, apiUrlInput].forEach(input => {
        input.addEventListener('input', checkInputs);
    });

    function checkInputs() {
        if (apiKeyInput.value.trim() && currentImageBase64 && apiUrlInput.value.trim()) {
            analyzeBtn.disabled = false;
        } else {
            analyzeBtn.disabled = true;
        }
    }

    analyzeBtn.addEventListener('click', async () => {
        // Reset UI
        errorContainer.classList.add('hidden');
        resultSection.classList.add('hidden');
        loadingIndicator.classList.remove('hidden');
        analyzeBtn.disabled = true;

        const apiKey = apiKeyInput.value.trim();
        const apiUrl = apiUrlInput.value.trim();

        const payload = {
            image_b64: currentImageBase64,
            location: [26.305, 50.146],
            api_key: apiKey,
            api_url: apiUrl
        };

        // Start Timer
        const activeTimerSpan = document.getElementById('activeTimer');
        let seconds = 0;
        activeTimerSpan.textContent = '0';
        const timerInterval = setInterval(() => {
            seconds++;
            activeTimerSpan.textContent = seconds;
        }, 1000);

        const startTime = performance.now();

        try {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            clearInterval(timerInterval);
            const duration = ((performance.now() - startTime) / 1000).toFixed(1);
            document.getElementById('finalTime').textContent = `(${duration}s)`;

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Server error: ${response.status} ${response.statusText}`);
            }

            const result = await response.json();
            const data = result.data || result;
            const report = data.vlm_report || {};

            if (report) {
                displayResults(data); // Pass data root to handle detections
            } else {
                throw new Error("Invalid API response: 'vlm_report' key missing.");
            }

        } catch (err) {
            console.error(err);
            showError(err.message || "An error occurred while connecting to the API. Make sure the server is running and CORS is configured if accessing directly from browser.");
        } finally {
            loadingIndicator.classList.add('hidden');
            analyzeBtn.disabled = false;
        }
    });

    function showError(msg) {
        errorContainer.textContent = msg;
        errorContainer.classList.remove('hidden');
    }

    function displayResults(data) {
        // Handle new response format: {"report": {"summary": "...", "boxes": [...], "report_markdown": "..."}}
        const report = data.report || {};
        const boxes = report.boxes || [];

        // Display Image on Canvas
        const canvas = document.getElementById('resultCanvas');
        if (canvas && currentImageDataUrl) {
            const ctx = canvas.getContext('2d');
            const img = new Image();
            img.onload = () => {
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);

                // Draw bounding boxes
                if (boxes.length > 0) {
                    boxes.forEach(box => {
                        if (box.bbox_xyxy && box.bbox_xyxy.length === 4) {
                            // New format: absolute pixels [ymin, xmin, ymax, xmax] -> actually looking at the data: [434, 665, 978, 768]
                            // Judging by typical outputs, it's [xmin, ymin, xmax, ymax]
                            const [x1, y1, x2, y2] = box.bbox_xyxy;

                            // Scale from original image dimensions to canvas dimensions
                            const scaleX = canvas.width / img.width;
                            const scaleY = canvas.height / img.height;

                            const rx1 = x1 * scaleX;
                            const ry1 = y1 * scaleY;
                            const rx2 = x2 * scaleX;
                            const ry2 = y2 * scaleY;

                            const width = rx2 - rx1;
                            const height = ry2 - ry1;

                            // Determine color based on severity
                            const severity = (box.severity || 'low').toLowerCase();
                            let color = '#22c55e'; // green (low)
                            if (severity === 'high') color = '#ef4444'; // red
                            else if (severity === 'moderate' || severity === 'medium') color = '#f97316'; // orange

                            // Draw rectangle
                            ctx.strokeStyle = color;
                            ctx.lineWidth = Math.max(6, Math.floor(canvas.width / 150));
                            ctx.strokeRect(rx1, ry1, width, height);

                            // Draw text background
                            const labelText = `${box.label || box.class || 'Defect'}`;
                            const fontSize = Math.max(20, Math.floor(canvas.width / 50));
                            ctx.font = `bold ${fontSize}px sans-serif`;
                            const textMetrics = ctx.measureText(labelText);
                            const textWidth = textMetrics.width;
                            const textHeight = fontSize;

                            ctx.fillStyle = color;
                            const boxY = Math.max(0, ry1 - textHeight - 12);
                            ctx.fillRect(rx1 - (ctx.lineWidth / 2), boxY, textWidth + 16, textHeight + 12);

                            ctx.fillStyle = '#ffffff';
                            ctx.fillText(labelText, rx1 + 4, boxY + textHeight + 2);
                        }
                    });
                }

                // Sync after image and boxes are completely drawn
                syncToSupabase(data);
            };
            img.src = currentImageDataUrl;
        } else {
            // Sync immediately if no image/canvas
            syncToSupabase(data);
        }

        document.getElementById('reportSummary').textContent = report.summary || "Analysis successful";

        // Engineering Report (Markdown)
        const markdownContainer = document.getElementById('markdownReportContainer');
        if (markdownContainer) {
            const mdContent = report.report_markdown || '';
            markdownContainer.innerHTML = marked.parse(mdContent);
        }

        // Recommended Actions
        const actionsList = document.getElementById('recommendedActionsList');
        actionsList.innerHTML = '';
        if (report.severities && report.severities.length > 0) {
            report.severities.forEach(item => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${item.defect}</strong>: ${item.reason}`;
                actionsList.appendChild(li);
            });
        } else {
            const li = document.createElement('li');
            li.textContent = "Maintain regular monitoring schedule";
            actionsList.appendChild(li);
        }

        // Boxes Table
        const tbody = document.querySelector('#boxesTable tbody');
        tbody.innerHTML = '';
        if (boxes.length > 0) {
            boxes.forEach((box, idx) => {
                const tr = document.createElement('tr');
                const severity = (box.severity || 'low').toLowerCase();

                tr.innerHTML = `
                    <td style="font-weight:700">${box.id || idx + 1}</td>
                    <td>${box.label || box.class || 'Defect'}</td>
                    <td class="severity-${severity}">${box.severity || 'Low'}</td>
                `;
                tbody.appendChild(tr);
            });
        } else {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center">No features detected.</td></tr>';
        }

        resultSection.classList.remove('hidden');

        // Scroll to results
        resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function syncToSupabase(data) {
        const canvas = document.getElementById('resultCanvas');
        const processedImageBase64 = canvas.toDataURL('image/jpeg', 0.8).split(',')[1];

        // Handle new API Format
        const report = data.report || data.vlm_report || {};
        const boxes = report.boxes || data.detections || [];
        const md = report.report_markdown || '';

        // Create a thumbnail for local history (to save localStorage space)
        const thumbCanvas = document.createElement('canvas');
        const scale = 300 / canvas.width;
        thumbCanvas.width = 300;
        thumbCanvas.height = canvas.height * scale;
        const thumbCtx = thumbCanvas.getContext('2d');
        thumbCtx.drawImage(canvas, 0, 0, thumbCanvas.width, thumbCanvas.height);
        const thumbDataUrl = thumbCanvas.toDataURL('image/jpeg', 0.5);

        // Track locally for the Dashboard Map & Grid
        trackHistoricalAnalysis(boxes, report.summary || '', thumbDataUrl);

        try {
            await fetch('/api/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    image_name: `bridge_${Date.now()}.jpg`,
                    processed_image_base64: processedImageBase64,
                    detection_count: boxes.length,
                    max_confidence: 0.85,
                    severity: boxes.some(b => b.severity === 'high') ? 'High' : 'Moderate',
                    boxes: boxes,
                    report_markdown: md,
                    location: {
                        "lat": 26.3073,
                        "lon": 50.1456
                    }
                })
            });
            console.log('Synced to Supabase via Bridge server');
        } catch (err) {
            console.warn('Supabase sync from standalone failed (Bridge server unreachable?):', err);
        }
    }

    // ==========================================
    // Tab Navigation Logic
    // ==========================================
    const tabs = document.querySelectorAll('.nav-links li');
    const tabContents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            tab.classList.add('active');
            const targetId = tab.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');

            // Force map resize when tab becomes visible. Leaflet needs this if loaded while hidden.
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

    // ==========================================
    // Historical Analysis Dashboard Tracking
    // ==========================================
    let localHistory = [];
    let dashboardMarkers = [];

    async function loadHistoricalAnalysis() {
        try {
            const res = await fetch('/api/history');
            if (res.ok) {
                localHistory = await res.json();
                updateDashboardKPI();
            }
        } catch (e) {
            console.error('Failed to load history', e);
        }
    }

    async function trackHistoricalAnalysis(boxes, summary, thumbUrl) {
        // Al-Khobar Base Coordinates center area:
        const AL_KHOBAR_LAT = 26.2833;
        const AL_KHOBAR_LON = 50.1983;

        // Randomize slightly around Al-Khobar for demo spread
        const plotLat = AL_KHOBAR_LAT + (Math.random() - 0.5) * 0.05;
        const plotLon = AL_KHOBAR_LON + (Math.random() - 0.5) * 0.05;

        let isHigh = boxes.some(b => (b.severity || '').toLowerCase() === 'high');
        let severityStatus = isHigh ? 'High Severity' : (boxes.length > 0 ? 'Moderate' : 'Low');

        const record = {
            lat: plotLat,
            lon: plotLon,
            severity: severityStatus,
            summary: summary,
            image: thumbUrl,
            timestamp: new Date().toISOString()
        };

        try {
            await fetch('/api/history', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(record)
            });
            await loadHistoricalAnalysis();
        } catch (e) {
            console.error('Failed to save history', e);
        }
    }

    function updateDashboardKPI() {
        document.getElementById('kpiTotal').textContent = localHistory.length;
        const criticalCount = localHistory.filter(h => h.severity === 'High Severity').length;
        document.getElementById('kpiCritical').textContent = criticalCount;

        if (window.dashboardMap) {
            dashboardMarkers.forEach(m => window.dashboardMap.removeLayer(m));
            dashboardMarkers = [];

            localHistory.forEach(record => {
                let color = '#22c55e'; // default green
                if (record.severity === 'High Severity') color = '#ef4444';
                else if (record.severity === 'Moderate') color = '#f59e0b';

                const marker = L.circleMarker([record.lat, record.lon], {
                    radius: 8,
                    fillColor: color,
                    color: '#fff',
                    weight: 2,
                    fillOpacity: 0.9
                }).bindPopup(`<b>${record.severity}</b><br/>${record.summary}`).addTo(window.dashboardMap);
                dashboardMarkers.push(marker);
            });
        }

        // Populate history grid
        const grid = document.getElementById('historyGrid');
        if (grid) {
            grid.innerHTML = '';
            // Render in reverse chronological order
            [...localHistory].reverse().forEach(record => {
                const card = document.createElement('div');
                card.className = 'history-card';

                let sevClass = record.severity === 'High Severity' ? 'high' :
                    record.severity === 'Moderate' ? 'moderate' : 'low';

                card.innerHTML = `
                    <img src="${record.image || 'https://via.placeholder.com/300x160?text=No+Image'}" alt="Analysis" />
                    <div class="history-card-content">
                        <div class="history-date">${new Date(record.timestamp).toLocaleString()}</div>
                        <div class="history-severity ${sevClass}">${record.severity}</div>
                        <div class="history-summary">${record.summary}</div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }
    }

    function initDashboardMap() {
        // Center on Al Khobar region
        const AL_KHOBAR_LAT = 26.2833;
        const AL_KHOBAR_LON = 50.1983;

        window.dashboardMap = L.map('kpiMap').setView([AL_KHOBAR_LAT, AL_KHOBAR_LON], 12);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO'
        }).addTo(window.dashboardMap);

        // Initial populate from history API
        loadHistoricalAnalysis();
    }

    // ==========================================
    // Mission Control Leaflet Map Initialization
    // ==========================================
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

        // Simulated flight path
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

    // ==========================================
    // Waypoints Leaflet Map Initialization
    // ==========================================
    function initWaypointMap() {
        const KFUPM_LAT = 26.3048;
        const KFUPM_LON = 50.1458;

        window.waypointMap = L.map('waypointMap', { zoomControl: true }).setView([KFUPM_LAT, KFUPM_LON], 17);
        // Force an immediate size invalidate to prevent breaking on load
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
            }).bindTooltip(`WP ${waypoints.length}`, { permanent: true, direction: "right" }).addTo(window.waypointMap);

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
                // Close the loop
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
            // Simplified planar area calculation for extremely small test area (50x50m)
            // Using Leaflet geometry util or basic math since 1 deg lat is ~111km
            let areaSqMeters = 0;
            if (points.length > 2 && typeof L.GeometryUtil !== 'undefined') {
                areaSqMeters = L.GeometryUtil.geodesicArea(points);
            } else {
                // Fallback math if GeometryUtil not loaded perfectly
                const R = 6378137; // radius
                let area = 0;
                let numPoints = points.length;
                let i, j;
                for (i = 0; i < numPoints; i++) {
                    j = (i + 1) % numPoints;
                    const p1 = points[i];
                    const p2 = points[j];
                    area += ((p2.lng - p1.lng) * Math.PI / 180) *
                        (2 + Math.sin(p1.lat * Math.PI / 180) + Math.sin(p2.lat * Math.PI / 180));
                }
                areaSqMeters = Math.abs(area * R * R / 2.0);
            }

            // User requested artificial underestimation (400% leniency, so multiply by 0.25)
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

    // Initialize maps after a short delay to ensure DOM is ready
    setTimeout(() => {
        if (typeof L !== 'undefined') {
            initMissionMap();
            initWaypointMap();
            initDashboardMap();
        }
    }, 500);

});

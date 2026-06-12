/*
 * Beach Lab DNA water-quality stations — persistent map markers.
 *
 * One marker per Chicago beach at its sample location, showing the most recent
 * DNA reading (source: data.cityofchicago.org/resource/hmqm-anjq, served via
 * GET /stations/beach-dna). Markers appear only when zoomed in a few steps
 * past the Dever Crib threshold (zoom 14) — see MIN_ZOOM below.
 */
(function() {
    var MIN_ZOOM = 15; 

    // Marker icon + green label styles
    var s = document.createElement('style');
    s.textContent = [
        '.ogrid-beach-marker{background:transparent;border:none;}',
        '.ogrid-beach-icon-wrap{width:26px;height:26px;background:#2e7d32;border:2px solid #ecf0f1;',
        '  border-radius:50%;display:flex;align-items:center;justify-content:center;',
        '  cursor:pointer;box-shadow:0 2px 5px rgba(0,0,0,0.5);}',
        '.ogrid-beach-icon-wrap .fa{color:#ecf0f1;font-size:12px;line-height:1;}',
        '.ogrid-beach-label.leaflet-tooltip{background:transparent!important;border:none!important;',
        '  box-shadow:none!important;color:#2e7d32!important;font-size:11px!important;',
        '  font-weight:bold!important;padding:3px 8px!important;white-space:nowrap!important;',
        '  text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,',
        '    -2px 0 0 #fff,2px 0 0 #fff,0 -2px 0 #fff,0 2px 0 #fff,0 2px 6px rgba(0,0,0,0.5)!important;}',
        '.ogrid-beach-label.leaflet-tooltip::before{display:none!important;}'
    ].join('');
    document.head.appendChild(s);

    var _icon = L.divIcon({
        className: 'ogrid-beach-marker',
        html: '<div class="ogrid-beach-icon-wrap"><i class="fa fa-tint"></i></div>',
        iconSize: [26, 26],
        iconAnchor: [13, 13],
        popupAnchor: [0, -16]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _fmtTime(ts) {
        if (!ts) return '';
        try { return moment(ts).format('MMM D, YYYY h:mm A'); }
        catch (e) { return String(ts).substring(0, 10); }
    }

    function _popupHtml(b, canvasId) {
        var val = parseFloat(b.dna_reading_mean);
        var elevated = !isNaN(val) && val >= 1000;
        var elevatedBadge = elevated
            ? ' <span style="color:#c62828;font-weight:bold;">(Elevated)</span>'
            : '';
        return '<b>' + _esc(b.beach) + '</b><br>' +
               '<b>DNA Reading Mean:</b> ' + _esc(b.dna_reading_mean) + elevatedBadge + '<br>' +
               '<span style="font-size:0.82em;opacity:0.7;">' + _esc(_fmtTime(b.timestamp)) + '</span>' +
               '<div style="margin-top:10px;">' +
                 '<b style="font-size:0.9em;">DNA Readings — Past 7 Days</b>' +
                 '<div style="position:relative;height:160px;margin-top:6px;">' +
                   '<canvas id="' + canvasId + '"></canvas>' +
                   '<div id="' + canvasId + '-loading" style="position:absolute;top:50%;left:50%;' +
                     'transform:translate(-50%,-50%);font-size:0.85em;opacity:0.6;">Loading…</div>' +
                 '</div>' +
                 '<div style="font-size:0.75em;opacity:0.6;margin-top:4px;">' +
                   'Dashed line = 1,000 cfu/100mL elevated threshold' +
                 '</div>' +
               '</div>';
    }

    function _drawDnaChart(canvasId, data) {
        var loadingEl = document.getElementById(canvasId + '-loading');
        if (loadingEl) { loadingEl.parentNode.removeChild(loadingEl); }

        var canvas = document.getElementById(canvasId);
        if (!canvas || !window.Chart) { return; }

        if (!data || !data.length) {
            var wrap = canvas.parentNode;
            if (wrap) {
                wrap.innerHTML = '<div style="text-align:center;opacity:0.6;padding:20px 0;font-size:0.85em;">' +
                                 'No readings in the past 7 days</div>';
            }
            return;
        }

        var labels = data.map(function(d) {
            try { return moment(d.timestamp).format('M/D h:mm A'); }
            catch (e) { return String(d.timestamp).substring(0, 10); }
        });
        var values = data.map(function(d) { return d.dna_reading_mean; });
        var threshold = data.map(function() { return 1000; });

        new window.Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'DNA Reading Mean',
                        data: values,
                        borderColor: '#1565c0',
                        backgroundColor: 'rgba(21,101,192,0.1)',
                        borderWidth: 2,
                        pointRadius: 3,
                        lineTension: 0.3,
                        fill: true,
                    },
                    {
                        label: 'Elevated Threshold (1,000)',
                        data: threshold,
                        borderColor: '#c62828',
                        borderWidth: 2,
                        borderDash: [6, 4],
                        pointRadius: 0,
                        fill: false,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                legend: { display: false },
                tooltips: {
                    callbacks: {
                        label: function(item, chartData) {
                            if (item.datasetIndex === 1) {
                                return 'Elevated threshold: 1,000 cfu/100mL';
                            }
                            return 'DNA Mean: ' + item.yLabel;
                        }
                    }
                },
                scales: {
                    xAxes: [{
                        ticks: {
                            maxTicksLimit: 6,
                            fontSize: 10,
                            maxRotation: 30,
                            minRotation: 0,
                        }
                    }],
                    yAxes: [{
                        ticks: { fontSize: 10, beginAtZero: true },
                        scaleLabel: { display: true, labelString: 'cfu/100mL', fontSize: 10 }
                    }]
                }
            }
        });
    }

    function _addBeach(b, map, state) {
        var marker = L.marker([b.latitude, b.longitude], {icon: _icon, zIndexOffset: 900})
            .bindTooltip(b.beach + ' Water Quality Tests', {
                permanent: true, direction: 'right',
                className: 'ogrid-beach-label', offset: [4, 0]
            });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: b.latitude,
                lon: b.longitude,
                title: b.beach + ' Water Quality Tests'
            });
        }
        marker.on('click', function() {
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            var canvasId = 'beach-dna-chart-' + Date.now();
            if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
                ogrid.App._rp.showStationContent({
                    title: b.beach + ' Water Quality Tests',
                    html: _popupHtml(b, canvasId)
                });
            }
            var histUrl = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') +
                          '/rest/stations/beach-dna/history?beach=' + encodeURIComponent(b.beach);
            $.ajax({ url: histUrl, type: 'GET', timeout: 20000 })
                .done(function(data) { _drawDnaChart(canvasId, data); })
                .fail(function() {
                    var loadingEl = document.getElementById(canvasId + '-loading');
                    if (loadingEl) { loadingEl.textContent = 'Chart unavailable.'; }
                });
        });
        state.markers.push(marker);
    }

    function _updateVisibility(map, state) {
        var show = map.getZoom() >= MIN_ZOOM;
        if (show && !state.onMap) {
            state.markers.forEach(function(m) { m.addTo(map); });
            state.onMap = true;
        } else if (!show && state.onMap) {
            state.markers.forEach(function(m) { m.remove(); });
            state.onMap = false;
        }
    }

    function init(map) {
        var state = { markers: [], onMap: false };
        var url = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest/stations/beach-dna';

        $.ajax({ url: url, type: 'GET', timeout: 15000 })
            .done(function(list) {
                (list || []).forEach(function(b) { _addBeach(b, map, state); });
                map.on('zoomend', function() { _updateVisibility(map, state); });
                _updateVisibility(map, state);
            });
    }

    // Wait for the Leaflet map, then load the beach stations
    var attempts = 0;
    var poll = setInterval(function() {
        attempts++;
        try {
            var map = ogrid.App.map().getMap();
            if (map) { clearInterval(poll); init(map); }
        } catch (e) {}
        if (attempts >= 30) clearInterval(poll);
    }, 500);
}());

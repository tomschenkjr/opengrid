/*
 * CivicFacilitiesLayer — persistent public facility markers.
 *
 * Libraries, police stations, fire stations, and speed cameras appear with CPS
 * schools at zoom 16+. Bike racks and park facilities/buildings appear after
 * bus stops; Park District art appears one step closer.
 */
(function () {
    var SCHOOL_ZOOM = 16;
    var AFTER_BUS_STOP_ZOOM = 18;
    var PARK_ART_ZOOM = 19;
    var _charts = [];

    var TYPES = [
        {
            id: 'libraries',
            label: 'Library',
            zoom: SCHOOL_ZOOM,
            color: '#0f766e',
            icon: 'fa-book',
            size: 22,
            fontSize: 11,
            z: 185
        },
        {
            id: 'police-stations',
            label: 'Police Station',
            zoom: SCHOOL_ZOOM,
            color: '#1d4ed8',
            icon: 'fa-building-shield',
            z: 186
        },
        {
            id: 'fire-stations',
            label: 'Fire Station',
            zoom: SCHOOL_ZOOM,
            color: '#dc2626',
            icon: 'fa-truck-medical',
            size: 22,
            fontSize: 11,
            z: 187
        },
        {
            id: 'speed-cameras',
            label: 'Speed Camera',
            zoom: AFTER_BUS_STOP_ZOOM,
            color: '#b45309',
            icon: 'fa-camera',
            z: 188
        },
        {
            id: 'bike-racks',
            label: 'Bike Rack',
            zoom: AFTER_BUS_STOP_ZOOM,
            color: '#16a34a',
            icon: 'fa-bicycle',
            z: 189
        },
        {
            id: 'park-facilities',
            label: 'Park Facility',
            zoom: AFTER_BUS_STOP_ZOOM,
            color: '#2f8f46',
            icon: 'fa-basketball-ball',
            z: 190
        },
        {
            id: 'park-buildings',
            label: 'Park Building',
            zoom: AFTER_BUS_STOP_ZOOM,
            color: '#64748b',
            icon: 'fa-building',
            z: 191
        },
        {
            id: 'park-art',
            label: 'Park District Art',
            zoom: PARK_ART_ZOOM,
            color: '#9333ea',
            icon: 'fa-paint-brush',
            z: 192
        }
    ];

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _type(typeId) {
        return TYPES.filter(function(t) { return t.id === typeId; })[0] || TYPES[0];
    }

    function _icon(type) {
        var size = type.size || 18;
        var anchor = Math.round(size / 2);
        var popup = anchor + 2;
        var fontSize = type.fontSize || 8;
        return L.divIcon({
            className: 'ogrid-facility-marker ogrid-facility-' + type.id,
            html: '<div class="ogrid-facility-icon-wrap" style="width:' + size + 'px;height:' + size +
                  'px;background:' + type.color + '">' +
                  '<i class="fa ' + type.icon + '" style="font-size:' + fontSize + 'px"></i>' +
                  '</div>',
            iconSize: [size, size],
            iconAnchor: [anchor, anchor],
            popupAnchor: [0, -popup]
        });
    }

    function _row(label, value) {
        if (value == null || value === '') {
            return '';
        }
        return '<div class="rc-row"><span class="rc-k">' + _esc(label) + '</span>' +
               '<span class="rc-v">' + _esc(value) + '</span></div>';
    }

    function _details(details) {
        return (details || []).map(function(d) {
            return _row(d.label, d.value);
        }).join('');
    }

    function _fmtNumber(value) {
        var n = Number(value);
        if (isNaN(n)) {
            return 'n/a';
        }
        return n.toLocaleString();
    }

    function _fmtDateTime(value) {
        if (!value) {
            return 'Time TBD';
        }
        var d = new Date(value);
        if (isNaN(d.getTime())) {
            return value;
        }
        return d.toLocaleString([], {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit'
        });
    }

    function _metricPoints(metric) {
        return (metric && metric.points || []).filter(function(point) {
            return point && point.label;
        });
    }

    function _hasMetric(metric) {
        return _metricPoints(metric).some(function(point) {
            return point.value != null && point.value !== '' && !isNaN(Number(point.value));
        });
    }

    function _canvasId(item, suffix) {
        return 'ogrid-library-chart-' + suffix + '-' + String(item.id || item.title || '')
            .replace(/[^a-zA-Z0-9_-]+/g, '-');
    }

    function _libraryMetricSection(item, metric, suffix) {
        if (!metric) {
            return '';
        }
        var canvasId = _canvasId(item, suffix);
        var total = metric.total != null ? _fmtNumber(metric.total) : 'n/a';
        return '<div class="ogrid-library-chart-section">' +
               '<div class="ogrid-library-chart-head">' +
               '<div class="ogrid-library-chart-title">2024 ' + _esc(metric.label || 'Metric') + '</div>' +
               '<div class="ogrid-library-chart-total">' + total + ' YTD</div>' +
               '</div>' +
               (_hasMetric(metric)
                    ? '<div class="ogrid-library-chart-wrap"><canvas id="' + _esc(canvasId) + '"></canvas></div>'
                    : '<div class="ogrid-library-chart-empty">No 2024 monthly data available.</div>') +
               '</div>';
    }

    function _libraryChartsHtml(item) {
        if (!item || item.kind !== 'libraries') {
            return '';
        }
        return _libraryMetricSection(item, item.library_visitors_2024, 'visitors') +
               _libraryMetricSection(item, item.library_circulation_2024, 'circulation');
    }

    function _libraryEventsHtml(item) {
        var events = item && item.library_events || [];
        if (!events.length) {
            return '';
        }
        var rows = events.map(function(event) {
            var id = event.event_id || event.id || '';
            return '<a class="ogrid-library-event-link" href="#/announcements/' + encodeURIComponent(id) + '">' +
                   _esc(event.title || 'Library Event') +
                   '<span>' + _esc(_fmtDateTime(event.start)) + '</span>' +
                   '</a>';
        }).join('');
        return '<div class="ogrid-library-events-section">' +
               '<div class="ogrid-library-events-title">Upcoming Events</div>' +
               rows +
               '<a class="ogrid-library-events-all" href="#/announcements">View all library events</a>' +
               '</div>';
    }

    function _detailCard(item) {
        var type = _type(item.kind);
        var rows = _details(item.details);
        return '<div class="ogrid-result-card ogrid-facility-result-card expanded" style="border-left-color:' + type.color + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(item.title || type.label) + '</div>' +
               '<div class="rc-top-right"><span class="rc-pill ogrid-facility-pill" style="color:' + type.color + ';border-color:' + type.color + '">' +
               _esc(item.pill || type.label) + '</span></div>' +
               '</div>' +
               (item.subtitle ? '<div class="rc-sub">' + _esc(item.subtitle) + '</div>' : '') +
               '<div class="rc-details">' + (rows || '<div class="rc-row">No details available.</div>') + '</div>' +
               _libraryChartsHtml(item) +
               _libraryEventsHtml(item) +
               '</div>';
    }

    function _destroyCharts() {
        _charts.forEach(function(chart) {
            if (chart && chart.destroy) {
                chart.destroy();
            }
        });
        _charts = [];
    }

    function _renderMetricChart(item, metric, suffix, color) {
        if (!window.Chart || !_hasMetric(metric)) {
            return;
        }
        var canvas = document.getElementById(_canvasId(item, suffix));
        if (!canvas) {
            return;
        }
        var points = _metricPoints(metric);
        var values = points.map(function(point) {
            var n = Number(point.value);
            return isNaN(n) ? null : n;
        });
        _charts.push(new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: points.map(function(point) { return point.label; }),
                datasets: [{
                    label: metric.label || 'Value',
                    data: values,
                    borderColor: color,
                    backgroundColor: color === '#0f766e' ? 'rgba(15,118,110,0.12)' : 'rgba(37,99,235,0.12)',
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 4,
                    pointHitRadius: 8,
                    lineTension: 0.25,
                    spanGaps: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                legend: { display: false },
                tooltips: {
                    callbacks: {
                        label: function(item) {
                            return _fmtNumber(item.yLabel);
                        }
                    }
                },
                scales: {
                    xAxes: [{ gridLines: { display: false }, ticks: { fontSize: 10 } }],
                    yAxes: [{ gridLines: { color: 'rgba(148,163,184,0.18)' },
                              ticks: { callback: _fmtNumber, fontSize: 10 } }]
                },
                layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } }
            }
        }));
    }

    function _renderLibraryCharts(item) {
        if (!item || item.kind !== 'libraries') {
            return;
        }
        _renderMetricChart(item, item.library_visitors_2024, 'visitors', '#0f766e');
        _renderMetricChart(item, item.library_circulation_2024, 'circulation', '#2563eb');
    }

    function _showFacility(item) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            _destroyCharts();
            ogrid.App._rp.showStationContent({
                title: item.kind_label || _type(item.kind).label,
                html: _detailCard(item)
            });
            window.setTimeout(function() {
                _renderLibraryCharts(item);
            }, 0);
        }
    }

    function _buildMarker(item) {
        var type = _type(item.kind);
        var marker = L.marker([item.lat, item.lon], {
            icon: _icon(type),
            zIndexOffset: type.z
        });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: item.lat,
                lon: item.lon,
                title: item.title || type.label
            });
        }
        marker.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            _showFacility(item);
        });
        return marker;
    }

    function _loadType(type, bounds, state, base) {
        state.groups[type.id].clearLayers();
        $.ajax({
            url: base + '/stations/facilities/' + type.id,
            data: {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: type.id === 'bike-racks' ? 25000 : 15000
        }).done(function(items) {
            (items || []).forEach(function(item) {
                _buildMarker(item).addTo(state.groups[type.id]);
            });
        });
    }

    function _updateType(map, state, base, type) {
        var group = state.groups[type.id];
        if (map.getZoom() >= type.zoom) {
            if (!state.onMap[type.id]) {
                group.addTo(map);
                state.onMap[type.id] = true;
            }
            _loadType(type, map.getBounds(), state, base);
        } else if (state.onMap[type.id]) {
            group.remove();
            group.clearLayers();
            state.onMap[type.id] = false;
        }
    }

    function _update(map, state, base) {
        TYPES.forEach(function(type) {
            _updateType(map, state, base, type);
        });
    }

    function _injectStyles() {
        if (document.getElementById('ogrid-facility-layer-style')) {
            return;
        }
        var s = document.createElement('style');
        s.id = 'ogrid-facility-layer-style';
        s.textContent =
            '.ogrid-facility-marker{background:transparent;border:none;}' +
            '.ogrid-facility-icon-wrap{width:18px;height:18px;border:2px solid #ecf0f1;' +
            'border-radius:50%;display:flex;align-items:center;justify-content:center;' +
            'cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,0.4);}' +
            '.ogrid-facility-icon-wrap .fa{color:#ecf0f1;font-size:8px;line-height:1;}' +
            '.ogrid-result-card.ogrid-facility-result-card{cursor:default;}' +
            '.ogrid-facility-pill{white-space:normal;text-align:left;}' +
            '.ogrid-library-chart-section{margin-top:12px;padding-top:10px;border-top:1px solid #e5e7eb;}' +
            '.ogrid-library-chart-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:6px;}' +
            '.ogrid-library-chart-title{font-size:12px;font-weight:700;color:#111827;}' +
            '.ogrid-library-chart-total{font-size:11px;font-weight:700;color:#64748b;white-space:nowrap;}' +
            '.ogrid-library-chart-wrap{height:132px;position:relative;}' +
            '.ogrid-library-chart-empty{font-size:12px;color:#64748b;padding:12px 0;}';
        document.head.appendChild(s);
    }

    function init(map) {
        _injectStyles();
        var state = { groups: {}, onMap: {} };
        TYPES.forEach(function(type) {
            state.groups[type.id] = L.layerGroup();
            state.onMap[type.id] = false;
        });
        var base = ogrid.Config.service.endpoint.replace(/\/rest\/?$/, '') + '/rest';

        map.on('moveend', function() { _update(map, state, base); });
        map.on('zoomend', function() { _update(map, state, base); });
        _update(map, state, base);
    }

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

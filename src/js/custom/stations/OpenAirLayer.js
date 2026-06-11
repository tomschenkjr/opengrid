/*
 * OpenAirLayer — persistent Open Air Chicago air-quality sensor markers.
 *
 * Sensors are fetched for the current map bounds from /stations/open-air-sensors
 * at the same zoom level as bus stops and Divvy stations. Clicking a sensor
 * loads its latest readings plus 24-hour history into the Results Pane.
 */
(function () {
    var OPEN_AIR_GREEN = '#22c55e';
    var AQI_YELLOW = '#f2c94c';
    var AQI_ORANGE = '#f2994a';
    var AQI_RED = '#d64545';
    var BLACK_CARBON = '#111111';
    var STOPS_ZOOM = 17;

    var _OPEN_AIR_ICON = L.divIcon({
        className: 'ogrid-openair-marker',
        html: '<div class="ogrid-openair-icon-wrap"><i class="fa fa-smog"></i></div>',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
        popupAnchor: [0, -12]
    });

    function _esc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _fmt(value) {
        if (value == null || value === '') {
            return 'n/a';
        }
        var n = Number(value);
        if (isNaN(n)) {
            return _esc(value);
        }
        if (Math.abs(n) >= 100) {
            return _esc(Math.round(n).toLocaleString());
        }
        return _esc((Math.round(n * 100) / 100).toLocaleString());
    }

    function _title(sensor) {
        return (sensor.sensor_name || 'Open Air Chicago') + ' Open Air Chicago Sensor';
    }

    function _canvasId(detail, group) {
        return 'openair-chart-' +
            String(detail.datasourceid || '').replace(/[^a-z0-9_-]/ig, '-') +
            '-' + String(group.id || '').replace(/[^a-z0-9_-]/ig, '-');
    }

    function _metricRows(values) {
        return (values || []).map(function(metric) {
            return '<div class="oa-metric-row">' +
                   '<span class="oa-metric-label">' + _esc(metric.label) + '</span>' +
                   '<span class="oa-metric-value">' + _fmt(metric.value) + '</span>' +
                   '</div>';
        }).join('');
    }

    function _numericValue(value) {
        if (value == null || value === '') {
            return null;
        }
        var n = Number(value);
        return isNaN(n) ? null : n;
    }

    function _pm25Color(value) {
        var n = _numericValue(value);
        if (n == null) {
            return OPEN_AIR_GREEN;
        }
        if (n <= 9.0) {
            return OPEN_AIR_GREEN;
        }
        if (n <= 35.4) {
            return AQI_YELLOW;
        }
        if (n <= 55.4) {
            return AQI_ORANGE;
        }
        return AQI_RED;
    }

    function _aqiIndexColor(value) {
        var n = _numericValue(value);
        if (n == null) {
            return OPEN_AIR_GREEN;
        }
        if (n <= 50) {
            return OPEN_AIR_GREEN;
        }
        if (n <= 100) {
            return AQI_YELLOW;
        }
        if (n <= 150) {
            return AQI_ORANGE;
        }
        return AQI_RED;
    }

    function _hexToRgba(hex, alpha) {
        var match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
        if (!match) {
            return 'rgba(34,197,94,' + alpha + ')';
        }
        return 'rgba(' + parseInt(match[1], 16) + ',' +
               parseInt(match[2], 16) + ',' +
               parseInt(match[3], 16) + ',' + alpha + ')';
    }

    function _groupColor(group) {
        if (!group) {
            return OPEN_AIR_GREEN;
        }
        if (group.id === 'pm25') {
            return _pm25Color(group.pill_value);
        }
        if (group.id === 'no2') {
            return _aqiIndexColor(group.pill_value);
        }
        if (group.id === 'black_carbon') {
            return BLACK_CARBON;
        }
        return group.color || OPEN_AIR_GREEN;
    }

    function _groupCard(detail, group) {
        var canvasId = _canvasId(detail, group);
        var color = _groupColor(group);
        return '<div class="ogrid-result-card ogrid-openair-result-card expanded" style="border-left-color:' + color + '">' +
               '<div class="rc-top">' +
               '<div class="rc-title">' + _esc(group.title) + '</div>' +
               '<div class="rc-top-right"><span class="rc-pill" style="border-color:' + color + ';color:' + color + '">' + _fmt(group.pill_value) + '</span></div>' +
               '</div>' +
               '<div class="oa-chart-wrap"><canvas id="' + _esc(canvasId) + '"></canvas></div>' +
               '<div class="oa-trend-label">' + _esc(group.trend_label || '') + ' past 24 hours</div>' +
               '<div class="oa-metrics">' + _metricRows(group.values) + '</div>' +
               '</div>';
    }

    function _detailHtml(detail) {
        if (!detail || !detail.groups || !detail.groups.length) {
            return '<div class="ogrid-empty">No recent readings available.</div>';
        }
        return detail.groups.map(function(group) {
            return _groupCard(detail, group);
        }).join('');
    }

    function _renderCharts(detail) {
        if (!window.Chart || !detail || !detail.groups) {
            return;
        }
        detail.groups.forEach(function(group) {
            var canvas = document.getElementById(_canvasId(detail, group));
            if (!canvas) {
                return;
            }
            var history = group.history || [];
            var labels = history.map(function(point) { return point.label || ''; });
            var values = history.map(function(point) {
                var v = Number(point.value);
                return isNaN(v) ? null : v;
            });
            var hasValue = values.some(function(v) { return v != null; });
            if (!hasValue) {
                $(canvas).replaceWith('<div class="oa-chart-empty">No 24-hour trend available.</div>');
                return;
            }
            var color = _groupColor(group);
            new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        data: values,
                        borderColor: color,
                        backgroundColor: _hexToRgba(color, 0.12),
                        borderWidth: 2,
                        pointRadius: 0,
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
                                return _fmt(item.yLabel);
                            }
                        }
                    },
                    scales: {
                        xAxes: [{ display: false, gridLines: { display: false } }],
                        yAxes: [{ display: false, gridLines: { display: false },
                                  ticks: { beginAtZero: false } }]
                    },
                    layout: { padding: { top: 4, right: 4, bottom: 0, left: 4 } }
                }
            });
        });
    }

    function _showLoading(sensor) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: _title(sensor),
                html: '<div class="ogrid-empty">Loading Open Air Chicago readings&hellip;</div>'
            });
        }
    }

    function _showDetail(detail) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: detail.title || _title(detail),
                html: _detailHtml(detail)
            });
            _renderCharts(detail);
        }
    }

    function _showError(sensor) {
        if (ogrid.App && ogrid.App._rp && ogrid.App._rp.showStationContent) {
            ogrid.App._rp.showStationContent({
                title: _title(sensor),
                html: '<div class="ogrid-empty">Open Air Chicago readings unavailable.</div>'
            });
        }
    }

    function _fetchDetail(sensor, base) {
        _showLoading(sensor);
        $.ajax({
            url: base + '/stations/open-air-sensor',
            data: { datasourceid: sensor.datasourceid },
            timeout: 20000
        }).done(function(detail) {
            _showDetail(detail);
        }).fail(function() {
            _showError(sensor);
        });
    }

    function _buildMarker(sensor, base) {
        var marker = L.marker([sensor.lat, sensor.lon], { icon: _OPEN_AIR_ICON, zIndexOffset: 210 });
        if (ogrid.StreetView) {
            ogrid.StreetView.attachToMarker(marker, {
                lat: sensor.lat,
                lon: sensor.lon,
                title: _title(sensor)
            });
        }
        marker.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            if (ogrid.StreetView) {
                ogrid.StreetView.openMarkerPopup(marker);
            }
            _fetchDetail(sensor, base);
        });
        return marker;
    }

    function _loadForBounds(bounds, state, base) {
        state.markerGroup.clearLayers();
        $.ajax({
            url: base + '/stations/open-air-sensors',
            data: {
                minLat: bounds.getSouth(), minLon: bounds.getWest(),
                maxLat: bounds.getNorth(), maxLon: bounds.getEast()
            },
            timeout: 20000
        }).done(function(sensors) {
            (sensors || []).forEach(function(sensor) {
                _buildMarker(sensor, base).addTo(state.markerGroup);
            });
        });
    }

    function _update(map, state, base) {
        var zoom = map.getZoom();
        if (zoom >= STOPS_ZOOM) {
            if (!state.onMap) {
                state.markerGroup.addTo(map);
                state.onMap = true;
            }
            _loadForBounds(map.getBounds(), state, base);
        } else if (state.onMap) {
            state.markerGroup.remove();
            state.markerGroup.clearLayers();
            state.onMap = false;
        }
    }

    function init(map) {
        var state = { markerGroup: L.layerGroup(), onMap: false };
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
